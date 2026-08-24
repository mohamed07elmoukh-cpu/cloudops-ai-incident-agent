from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from cloudops_agent.events.alertmanager import (
    AlertmanagerWebhook,
    alertmanager_to_cloud_events,
)
from cloudops_agent.events.models import CloudEventEnvelope
from cloudops_agent.events.queue import SqsEventQueue


def alertmanager_payload(
    *, fingerprint: str = "stable-fingerprint", source: str = "demo-service"
) -> dict[str, Any]:
    return {
        "receiver": "cloudops-webhook",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "DemoServiceHighCPU",
                    "service": source,
                    "severity": "high",
                    "metric_name": "demo_cpu_load_percent",
                    "threshold": "85",
                },
                "annotations": {"current_value": "92", "summary": "CPU high"},
                "startsAt": "2026-08-24T18:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": "http://prometheus:9090/graph",
                "fingerprint": fingerprint,
            }
        ],
        "groupLabels": {"alertname": "DemoServiceHighCPU"},
        "commonLabels": {"service": source},
        "commonAnnotations": {},
        "externalURL": "http://alertmanager:9093",
        "version": "4",
        "groupKey": f"cpu:{source}",
        "truncatedAlerts": 0,
    }


def valid_event_data() -> dict[str, Any]:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "METRIC_THRESHOLD_BREACHED",
        "source": "demo-service",
        "occurred_at": "2026-08-24T18:00:00Z",
        "severity": "HIGH",
        "correlation_key": "demo-service:cpu-saturation",
        "payload": {
            "metric_name": "demo_cpu_load_percent",
            "value": 92,
            "threshold": 85,
            "alert_status": "firing",
            "labels": {},
            "annotations": {},
        },
        "schema_version": "1.0",
        "trace_id": str(uuid.uuid4()),
    }


def test_alertmanager_conversion_creates_strict_cloud_event() -> None:
    webhook = AlertmanagerWebhook.model_validate(alertmanager_payload())

    event = alertmanager_to_cloud_events(webhook)[0]

    assert event.event_type == "METRIC_THRESHOLD_BREACHED"
    assert event.source == "demo-service"
    assert event.severity == "HIGH"
    assert event.correlation_key == "demo-service:cpu-saturation"
    assert event.payload["labels"]["alertname"] == "DemoServiceHighCPU"


def test_alertmanager_event_id_and_correlation_key_are_stable() -> None:
    webhook = AlertmanagerWebhook.model_validate(alertmanager_payload())

    first = alertmanager_to_cloud_events(webhook)[0]
    second = alertmanager_to_cloud_events(webhook)[0]

    assert first.event_id == second.event_id
    assert first.correlation_key == second.correlation_key
    assert first.trace_id == second.trace_id


def test_alertmanager_new_occurrence_gets_a_new_event_id() -> None:
    first_payload = alertmanager_payload()
    second_payload = alertmanager_payload()
    second_payload["alerts"][0]["startsAt"] = "2026-08-24T18:05:00Z"

    first = alertmanager_to_cloud_events(AlertmanagerWebhook.model_validate(first_payload))[0]
    second = alertmanager_to_cloud_events(AlertmanagerWebhook.model_validate(second_payload))[0]

    assert first.event_id != second.event_id
    assert first.correlation_key == second.correlation_key


def test_invalid_alertmanager_payload_is_rejected() -> None:
    payload = alertmanager_payload()
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        AlertmanagerWebhook.model_validate(payload)


def test_unknown_cloud_event_schema_version_is_rejected() -> None:
    payload = valid_event_data()
    payload["schema_version"] = "2.0"

    with pytest.raises(ValidationError):
        CloudEventEnvelope.model_validate_json(json.dumps(payload))


def test_unknown_cloud_event_field_is_rejected() -> None:
    payload = valid_event_data()
    payload["unknown"] = "forbidden"

    with pytest.raises(ValidationError):
        CloudEventEnvelope.model_validate_json(json.dumps(payload))


class RecordingSqsClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send_message(self, **kwargs: Any) -> dict[str, Any]:
        self.sent.append(kwargs)
        return {"MessageId": "sqs-message-1"}

    def receive_message(self, **kwargs: Any) -> dict[str, Any]:
        return {}

    def delete_message(self, **kwargs: Any) -> dict[str, Any]:
        return {}

    def get_queue_attributes(self, **kwargs: Any) -> dict[str, Any]:
        return {"Attributes": {"ApproximateNumberOfMessages": "0"}}


def test_sqs_event_queue_publishes_serialized_cloud_event() -> None:
    client = RecordingSqsClient()
    queue = SqsEventQueue("http://localstack/queue", client=client)
    event = CloudEventEnvelope.model_validate_json(json.dumps(valid_event_data()))

    message_id = queue.publish(event)

    assert message_id == "sqs-message-1"
    assert json.loads(client.sent[0]["MessageBody"])["event_id"] == str(event.event_id)
