from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from apps.api.main import app, get_event_queue
from cloudops_agent.events.queue import InMemoryEventQueue
from tests.unit.test_events import alertmanager_payload


def test_webhook_publishes_event_without_running_detection(client: TestClient) -> None:
    queue = InMemoryEventQueue()
    app.dependency_overrides[get_event_queue] = lambda: queue

    response = client.post("/api/webhooks/alertmanager", json=alertmanager_payload())

    assert response.status_code == 202
    assert response.json()["published"] == 1
    assert len(queue.messages) == 1
    assert client.get("/api/incidents").json() == []


def test_webhook_redelivery_is_idempotent(client: TestClient) -> None:
    queue = InMemoryEventQueue()
    app.dependency_overrides[get_event_queue] = lambda: queue
    payload = alertmanager_payload()

    first = client.post("/api/webhooks/alertmanager", json=payload)
    second = client.post("/api/webhooks/alertmanager", json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["duplicates"] == 1
    assert len(queue.messages) == 1


def test_webhook_handles_multiple_alerts(client: TestClient) -> None:
    queue = InMemoryEventQueue()
    app.dependency_overrides[get_event_queue] = lambda: queue
    payload = alertmanager_payload()
    second_alert: dict[str, Any] = dict(payload["alerts"][0])
    second_alert["fingerprint"] = "second-fingerprint"
    second_alert["labels"] = dict(second_alert["labels"], instance="worker-2")
    payload["alerts"].append(second_alert)

    response = client.post("/api/webhooks/alertmanager", json=payload)

    assert response.status_code == 202
    assert response.json()["accepted"] == 2
    assert response.json()["published"] == 2
    assert len(queue.messages) == 2


def test_webhook_rejects_invalid_alertmanager_payload(client: TestClient) -> None:
    app.dependency_overrides[get_event_queue] = lambda: InMemoryEventQueue()
    payload = alertmanager_payload()
    del payload["alerts"]

    response = client.post("/api/webhooks/alertmanager", json=payload)

    assert response.status_code == 422
