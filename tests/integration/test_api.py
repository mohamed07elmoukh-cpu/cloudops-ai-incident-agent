import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.api import main as api_main
from cloudops_agent.events.queue import InMemoryEventQueue
from cloudops_agent.models import ProcessedEvent


def cpu_payload(value: float = 92) -> dict[str, object]:
    return {
        "source": "demo-service",
        "metric_name": "cpu_usage_percent",
        "value": value,
        "threshold": 85,
        "timestamp": datetime(2026, 8, 24, 17, tzinfo=UTC).isoformat(),
    }


def test_health_and_incident_endpoints(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}

    detection = client.post("/api/detection/evaluate", json=cpu_payload())
    assert detection.status_code == 200
    incident_id = detection.json()["incident"]["id"]

    listed = client.get("/api/incidents")
    fetched = client.get(f"/api/incidents/{incident_id}")

    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert fetched.status_code == 200
    assert fetched.json()["incident_type"] == "CPU_SATURATION"


def test_api_loads_and_executes_selected_runbook(client: TestClient) -> None:
    detection = client.post("/api/detection/evaluate", json=cpu_payload())
    incident_id = detection.json()["incident"]["id"]

    response = client.post(
        f"/api/incidents/{incident_id}/remediate",
        json={"runbook_name": "scale_service"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "VERIFYING"
    assert response.json()["remediation_executions"][0]["runbook_name"] == "scale_service"


def test_incident_filters_pagination_statistics_and_timeline(
    client: TestClient, session: Session
) -> None:
    first = client.post("/api/detection/evaluate", json=cpu_payload()).json()["incident"]
    second_payload = cpu_payload()
    second_payload["source"] = "worker-service"
    client.post("/api/detection/evaluate", json=second_payload)

    filtered = client.get("/api/incidents", params={"status": "OPEN", "search": "demo"})
    assert filtered.status_code == 200
    assert filtered.headers["x-total-count"] == "1"
    assert len(filtered.json()) == 1

    paged = client.get("/api/incidents", params={"page": 2, "page_size": 1})
    assert paged.headers["x-total-count"] == "2"
    assert len(paged.json()) == 1

    event_id = uuid.uuid4()
    session.add(
        ProcessedEvent(
            event_id=event_id,
            event_type="METRIC_THRESHOLD_BREACHED",
            incident_id=uuid.UUID(first["id"]),
            status="PROCESSED",
            trace_id=uuid.uuid4(),
        )
    )
    session.commit()

    events = client.get(f"/api/incidents/{first['id']}/events")
    timeline = client.get(f"/api/incidents/{first['id']}/timeline")
    statistics = client.get("/api/statistics")

    assert events.status_code == 200
    assert events.json()[0]["event_id"] == str(event_id)
    assert {entry["kind"] for entry in timeline.json()} >= {"incident", "evidence", "event"}
    assert statistics.json()["total"] == 2
    assert statistics.json()["open"] == 2
    assert len(statistics.json()["daily_trend"]) == 14


def test_system_health_aggregates_database_queue_and_worker(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = InMemoryEventQueue()
    api_main.app.dependency_overrides[api_main.get_event_queue] = lambda: queue
    monkeypatch.setattr(api_main, "_worker_health", lambda: (True, None))

    response = client.get("/api/system/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert set(response.json()["components"]) == {"api", "postgresql", "sqs", "worker"}
    api_main.app.dependency_overrides.pop(api_main.get_event_queue, None)


def test_ec2_resource_incident_can_be_scaled_verified_and_resolved(
    client: TestClient,
) -> None:
    detection = client.post(
        "/api/detection/resources/evaluate",
        json={
            "resource_type": "EC2",
            "resource_id": "api-asg",
            "metric_name": "CPUUtilization",
            "value": 92,
            "threshold": 80,
            "condition": "above",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    incident = detection.json()["incident"]
    remediation = client.post(
        f"/api/incidents/{incident['id']}/remediate",
        json={
            "parameters": {
                "auto_scaling_group_name": "api-asg",
                "desired_capacity": 4,
            },
            "estimated_monthly_cost_delta_usd": 50,
        },
    )
    verification = client.post(
        f"/api/incidents/{incident['id']}/verify",
        json={"metric_name": "CPUUtilization", "value": 55},
    )

    assert detection.status_code == 200
    assert incident["incident_type"] == "EC2_CAPACITY_SATURATION"
    assert remediation.status_code == 200
    assert remediation.json()["remediation_executions"][0]["output"]["simulated"] is True
    assert verification.json()["status"] == "RESOLVED"


def test_rds_compute_requires_approval_and_supports_rollback(client: TestClient) -> None:
    incident = client.post(
        "/api/detection/resources/evaluate",
        json={
            "resource_type": "RDS",
            "resource_id": "orders-db",
            "metric_name": "CPUUtilization",
            "value": 95,
            "threshold": 80,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    ).json()["incident"]
    request = {
        "parameters": {
            "db_instance_identifier": "orders-db",
            "db_instance_class": "db.t3.large",
            "apply_immediately": False,
        },
        "estimated_monthly_cost_delta_usd": 100,
    }

    rejected = client.post(f"/api/incidents/{incident['id']}/remediate", json=request)
    request["approved_by"] = "ops@example.com"
    accepted = client.post(f"/api/incidents/{incident['id']}/remediate", json=request)
    execution = accepted.json()["remediation_executions"][0]

    assert rejected.status_code == 403
    assert accepted.status_code == 200
    rollback = client.post(
        f"/api/incidents/{incident['id']}/rollback",
        json={
            "execution_id": execution["id"],
            "approved_by": "ops@example.com",
        },
    )
    assert rollback.status_code == 200
    assert rollback.json()["status"] == "ESCALATED"
