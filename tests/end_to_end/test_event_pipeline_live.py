from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

import boto3
import httpx
import pytest
from botocore.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from cloudops_agent.models import Evidence, Incident, ProcessedEvent, PublishedEvent

API_URL = os.getenv("LIVE_API_URL", "http://localhost:8000")
FAULTY_URL = os.getenv("LIVE_FAULTY_URL", "http://localhost:8001")
PROMETHEUS_URL = os.getenv("LIVE_PROMETHEUS_URL", "http://localhost:9090")
WORKER_URL = os.getenv("LIVE_WORKER_URL", "http://localhost:8002")
LOCALSTACK_URL = os.getenv("LIVE_LOCALSTACK_URL", "http://localhost:4567")
DATABASE_URL = os.getenv(
    "LIVE_DATABASE_URL",
    "postgresql+psycopg://cloudops:cloudops@localhost:55432/cloudops?connect_timeout=2",
)


def wait_for[T](description: str, timeout: float, probe: Callable[[], T | None]) -> T:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = probe()
            if result is not None:
                return result
        except Exception as exc:
            last_error = exc
        time.sleep(1)
    detail = f"; last error: {last_error}" if last_error else ""
    pytest.fail(f"timeout waiting for {description} after {timeout:.0f}s{detail}")


def prometheus_alerts(client: httpx.Client) -> list[dict[str, Any]]:
    response = client.get(f"{PROMETHEUS_URL}/api/v1/alerts")
    response.raise_for_status()
    return cast(list[dict[str, Any]], response.json()["data"]["alerts"])


def firing_cpu_alert(client: httpx.Client) -> dict[str, Any] | None:
    for alert in prometheus_alerts(client):
        if (
            alert.get("labels", {}).get("alertname") == "DemoServiceHighCPU"
            and alert.get("state") == "firing"
        ):
            return alert
    return None


def worker_received_count(client: httpx.Client) -> float:
    response = client.get(f"{WORKER_URL}/metrics")
    response.raise_for_status()
    match = re.search(r"^cloudops_events_received_total ([0-9.]+)$", response.text, re.MULTILINE)
    return float(match.group(1)) if match else 0.0


def test_real_faulty_service_to_postgresql_event_pipeline() -> None:
    http = httpx.Client(timeout=3)
    database_engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    sqs = boto3.client(
        "sqs",
        endpoint_url=LOCALSTACK_URL,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 1}),
    )
    try:
        for url in (f"{API_URL}/health", f"{FAULTY_URL}/health", f"{WORKER_URL}/health"):
            response = http.get(url)
            response.raise_for_status()
        http.get(f"{PROMETHEUS_URL}/-/healthy").raise_for_status()
        with database_engine.connect():
            pass
        queue_url = sqs.get_queue_url(QueueName="cloudops-incidents")["QueueUrl"].replace(
            "http://localstack:4566", LOCALSTACK_URL
        )
    except Exception:
        http.close()
        database_engine.dispose()
        pytest.skip("the seven-service live stack is not available")

    try:
        wait_for(
            "any previous CPU alert to resolve",
            60,
            lambda: True if firing_cpu_alert(http) is None else None,
        )
        started_at = datetime.now(UTC)
        received_before = worker_received_count(http)
        response = http.post(f"{FAULTY_URL}/chaos/cpu", params={"duration_seconds": 45})
        assert response.status_code == 202, response.text

        alert = wait_for("DemoServiceHighCPU to become firing", 40, lambda: firing_cpu_alert(http))
        assert alert["labels"]["service"] == "demo-service"

        def find_publication() -> PublishedEvent | None:
            with Session(database_engine) as session:
                return session.scalar(
                    select(PublishedEvent)
                    .where(PublishedEvent.published_at >= started_at)
                    .order_by(PublishedEvent.published_at.desc())
                    .limit(1)
                )

        publication = wait_for("Alertmanager webhook SQS publication", 15, find_publication)
        assert publication.message_id

        def find_processed() -> ProcessedEvent | None:
            with Session(database_engine) as session:
                return session.get(ProcessedEvent, publication.event_id)

        processed = wait_for("incident worker commit", 20, find_processed)
        assert processed.status == "PROCESSED"
        assert processed.incident_id is not None

        with Session(database_engine) as session:
            incident = session.get(Incident, processed.incident_id)
            evidence = session.scalar(
                select(Evidence)
                .where(Evidence.incident_id == processed.incident_id)
                .order_by(Evidence.timestamp.desc())
                .limit(1)
            )
            assert incident is not None
            assert incident.incident_type == "CPU_SATURATION"
            assert evidence is not None
            assert evidence.metric_value > 85

        wait_for(
            "worker received metric increment",
            10,
            lambda: worker_received_count(http)
            if worker_received_count(http) > received_before
            else None,
        )

        def main_queue_empty() -> bool | None:
            attributes = sqs.get_queue_attributes(
                QueueUrl=queue_url,
                AttributeNames=[
                    "ApproximateNumberOfMessages",
                    "ApproximateNumberOfMessagesNotVisible",
                ],
            )["Attributes"]
            visible = int(attributes.get("ApproximateNumberOfMessages", 0))
            in_flight = int(attributes.get("ApproximateNumberOfMessagesNotVisible", 0))
            return True if visible == 0 and in_flight == 0 else None

        assert wait_for("main incident queue to drain", 15, main_queue_empty)
    finally:
        http.close()
        database_engine.dispose()
