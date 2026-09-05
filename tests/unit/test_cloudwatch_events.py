from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from cloudops_agent.events.cloudwatch import (
    cloudwatch_alarm_to_cloud_event,
    decode_event_message,
)
from cloudops_agent.events.consumer import IncidentWorker
from cloudops_agent.events.queue import InMemoryEventQueue
from cloudops_agent.models import Incident, ProcessedEvent


def cloudwatch_event(
    *,
    namespace: str = "AWS/EC2",
    metric_name: str = "CPUUtilization",
    dimensions: dict[str, str] | None = None,
    value: float = 92,
    threshold: float = 80,
    comparison_operator: str = "GreaterThanThreshold",
) -> dict[str, Any]:
    return {
        "version": "0",
        "id": "1da8c9e8-2d9b-4e45-b6fa-4fe617bd9f64",
        "detail-type": "CloudWatch Alarm State Change",
        "source": "aws.cloudwatch",
        "account": "123456789012",
        "time": "2026-09-05T12:00:00Z",
        "region": "eu-west-1",
        "resources": ["arn:aws:cloudwatch:eu-west-1:123456789012:alarm:cloudops-api-cpu"],
        "detail": {
            "alarmName": "cloudops-api-cpu",
            "state": {
                "value": "ALARM",
                "reason": "Threshold crossed",
                "reasonData": json.dumps(
                    {
                        "threshold": threshold,
                        "evaluatedDatapoints": [
                            {"timestamp": "2026-09-05T11:59:00Z", "value": value}
                        ],
                    }
                ),
            },
            "previousState": {"value": "OK"},
            "configuration": {
                "comparisonOperator": comparison_operator,
                "metrics": [
                    {
                        "id": "m1",
                        "metricStat": {
                            "metric": {
                                "namespace": namespace,
                                "name": metric_name,
                                "dimensions": dimensions
                                or {"AutoScalingGroupName": "api-production-asg"},
                            },
                            "period": 60,
                            "stat": "Average",
                        },
                        "returnData": True,
                    }
                ],
            },
        },
    }


def test_normalizes_native_ec2_alarm_event() -> None:
    event = cloudwatch_alarm_to_cloud_event(cloudwatch_event())

    assert event.event_type == "AWS_RESOURCE_THRESHOLD_BREACHED"
    assert str(event.event_id) == "1da8c9e8-2d9b-4e45-b6fa-4fe617bd9f64"
    assert event.occurred_at == datetime.fromisoformat("2026-09-05T12:00:00+00:00")
    assert event.payload["resource_type"] == "EC2"
    assert event.payload["resource_id"] == "api-production-asg"
    assert event.payload["value"] == 92
    assert event.payload["threshold"] == 80


def test_normalizes_dynamodb_and_rds_alarm_dimensions() -> None:
    dynamodb = cloudwatch_alarm_to_cloud_event(
        cloudwatch_event(
            namespace="AWS/DynamoDB",
            metric_name="ReadThrottleEvents",
            dimensions={"TableName": "orders"},
        )
    )
    rds = cloudwatch_alarm_to_cloud_event(
        cloudwatch_event(
            namespace="AWS/RDS",
            metric_name="FreeStorageSpace",
            dimensions={"DBInstanceIdentifier": "orders-db"},
            value=8_000_000_000,
            threshold=10_000_000_000,
            comparison_operator="LessThanThreshold",
        )
    )

    assert dynamodb.payload["resource_type"] == "DYNAMODB"
    assert dynamodb.payload["resource_id"] == "orders"
    assert rds.payload["resource_type"] == "RDS"
    assert rds.payload["resource_id"] == "orders-db"
    assert rds.payload["condition"] == "below"


def test_rejects_non_alarm_and_unsupported_metric() -> None:
    not_alarm = cloudwatch_event()
    not_alarm["detail"]["state"]["value"] = "OK"
    unsupported = cloudwatch_event(namespace="Custom/App")

    with pytest.raises(ValueError, match="only CloudWatch ALARM"):
        cloudwatch_alarm_to_cloud_event(not_alarm)
    with pytest.raises(ValueError, match="no supported"):
        cloudwatch_alarm_to_cloud_event(unsupported)


def test_decoder_keeps_existing_internal_cloud_event_contract() -> None:
    normalized = cloudwatch_alarm_to_cloud_event(cloudwatch_event())

    decoded = decode_event_message(normalized.model_dump_json())

    assert decoded == normalized


def session_factory(engine: Engine) -> Callable[[], Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_worker_consumes_native_eventbridge_message(engine: Engine) -> None:
    queue = InMemoryEventQueue()
    queue.publish_raw(json.dumps(cloudwatch_event()))
    worker = IncidentWorker(queue, session_factory(engine))

    assert worker.run_once(wait_time_seconds=0) == 1

    with Session(engine) as session:
        incident = session.scalar(select(Incident))
        processed = session.scalar(select(ProcessedEvent))
        assert incident is not None
        assert incident.source == "api-production-asg"
        assert incident.incident_type == "EC2_CAPACITY_SATURATION"
        assert incident.evidence[0].raw_data["cloud_event"]["payload"]["alarm_name"] == (
            "cloudops-api-cpu"
        )
        assert processed is not None
        assert processed.status == "PROCESSED"
    assert len(queue.deleted_receipts) == 1
