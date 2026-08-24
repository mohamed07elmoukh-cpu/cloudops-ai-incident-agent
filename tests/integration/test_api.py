from datetime import UTC, datetime

from fastapi.testclient import TestClient


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

