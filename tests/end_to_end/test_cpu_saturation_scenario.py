from datetime import UTC, datetime

from fastapi.testclient import TestClient


def test_cpu_saturation_to_resolved(client: TestClient) -> None:
    detection = client.post(
        "/api/detection/evaluate",
        json={
            "source": "demo-service",
            "metric_name": "cpu_usage_percent",
            "value": 92,
            "threshold": 85,
            "timestamp": datetime(2026, 8, 24, 17, tzinfo=UTC).isoformat(),
        },
    )
    assert detection.status_code == 200
    assert detection.json()["incident_created"] is True
    assert detection.json()["incident"]["status"] == "OPEN"
    incident_id = detection.json()["incident"]["id"]

    open_incident = client.get(f"/api/incidents/{incident_id}")
    assert open_incident.status_code == 200
    assert open_incident.json()["status"] == "OPEN"

    remediation = client.post(f"/api/incidents/{incident_id}/remediate", json={})
    assert remediation.status_code == 200
    assert remediation.json()["status"] == "VERIFYING"

    verification = client.post(
        f"/api/incidents/{incident_id}/verify",
        json={"value": 55},
    )
    assert verification.status_code == 200
    assert verification.json()["status"] == "RESOLVED"
    assert verification.json()["resolved_at"] is not None
    assert verification.json()["remediation_executions"][0]["status"] == "SUCCEEDED"

