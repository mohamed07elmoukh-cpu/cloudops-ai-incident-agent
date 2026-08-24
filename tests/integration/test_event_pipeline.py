from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from cloudops_agent.database import Base
from cloudops_agent.events.consumer import IncidentWorker
from cloudops_agent.events.models import CloudEventEnvelope
from cloudops_agent.events.queue import SqsClientProtocol, SqsEventQueue
from cloudops_agent.models import Incident, ProcessedEvent, Severity

LOCALSTACK_ENDPOINT = os.getenv("TEST_AWS_ENDPOINT_URL", "http://localhost:4567")
POSTGRES_TEST_URL = os.getenv(
    "TEST_POSTGRES_URL",
    "postgresql+psycopg://cloudops:cloudops@localhost:55432/cloudops_test?connect_timeout=2",
)


def sqs_client() -> SqsClientProtocol:
    return cast(
        SqsClientProtocol,
        boto3.client(
            "sqs",
            endpoint_url=LOCALSTACK_ENDPOINT,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
            config=Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 1}),
        ),
    )


def integration_event(source: str) -> CloudEventEnvelope:
    return CloudEventEnvelope.model_validate(
        {
            "event_id": uuid.uuid4(),
            "event_type": "METRIC_THRESHOLD_BREACHED",
            "source": source,
            "occurred_at": datetime.now(UTC),
            "severity": Severity.HIGH,
            "correlation_key": f"{source}:cpu-saturation",
            "payload": {
                "metric_name": "demo_cpu_load_percent",
                "value": 92,
                "threshold": 85,
                "alert_status": "firing",
                "labels": {"service": source},
                "annotations": {},
            },
            "schema_version": "1.0",
            "trace_id": uuid.uuid4(),
        }
    )


def wait_for_visible_message(client: SqsClientProtocol, queue_url: str, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        count = int(response.get("Attributes", {}).get("ApproximateNumberOfMessages", 0))
        if count:
            return count
        time.sleep(0.2)
    return 0


def host_queue_url(queue_url: str) -> str:
    return queue_url.replace("http://localstack:4566", LOCALSTACK_ENDPOINT)


def test_postgresql_localstack_consumption_idempotence_and_dlq() -> None:
    client = sqs_client()
    postgres_engine = create_engine(POSTGRES_TEST_URL, pool_pre_ping=True)
    try:
        client.get_queue_url(QueueName="cloudops-incidents")  # type: ignore[attr-defined]
        with postgres_engine.connect():
            pass
    except (BotoCoreError, ClientError, OperationalError):
        postgres_engine.dispose()
        pytest.skip("PostgreSQL and LocalStack integration services are not available")

    Base.metadata.create_all(postgres_engine)
    suffix = uuid.uuid4().hex[:10]
    dlq_name = f"cloudops-test-dlq-{suffix}"
    queue_name = f"cloudops-test-{suffix}"
    dlq_url = host_queue_url(
        str(client.create_queue(QueueName=dlq_name)["QueueUrl"])  # type: ignore[attr-defined]
    )
    dlq_attributes = client.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])
    dlq_arn = str(dlq_attributes["Attributes"]["QueueArn"])
    queue_url = host_queue_url(
        str(
            client.create_queue(  # type: ignore[attr-defined]
                QueueName=queue_name,
                Attributes={
                    "VisibilityTimeout": "0",
                    "RedrivePolicy": json.dumps(
                        {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "3"}
                    ),
                },
            )["QueueUrl"]
        )
    )
    queue = SqsEventQueue(queue_url, client=client, visibility_timeout=0)
    sessions = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    session_factory: Callable[[], Session] = sessions
    worker = IncidentWorker(queue, session_factory)
    source = f"integration-{suffix}"
    event = integration_event(source)

    try:
        queue.publish(event)
        assert wait_for_visible_message(client, queue_url, 5) == 1
        assert worker.run_once(wait_time_seconds=1) == 1

        with Session(postgres_engine) as session:
            incident_count = session.scalar(
                select(func.count()).select_from(Incident).where(Incident.source == source)
            )
            processed = session.get(ProcessedEvent, event.event_id)
            assert incident_count == 1
            assert processed is not None
            assert processed.incident_id is not None

        queue.publish(event)
        assert worker.run_once(wait_time_seconds=1) == 1
        with Session(postgres_engine) as session:
            incident_count = session.scalar(
                select(func.count()).select_from(Incident).where(Incident.source == source)
            )
            processed_count = session.scalar(
                select(func.count())
                .select_from(ProcessedEvent)
                .where(ProcessedEvent.event_id == event.event_id)
            )
            assert incident_count == 1
            assert processed_count == 1

        client.send_message(QueueUrl=queue_url, MessageBody='{ "invalid": true }')
        for _ in range(4):
            worker.run_once(wait_time_seconds=1)
        assert wait_for_visible_message(client, dlq_url, 5) == 1
        assert queue.approximate_counts() == (0, 0)
    finally:
        client.delete_queue(QueueUrl=queue_url)  # type: ignore[attr-defined]
        client.delete_queue(QueueUrl=dlq_url)  # type: ignore[attr-defined]
        postgres_engine.dispose()
