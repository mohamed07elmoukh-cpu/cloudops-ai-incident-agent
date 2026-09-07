from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi.testclient import TestClient

from cloudops_agent.schemas import CostEstimateRead


def create_resource_incident(
    client: TestClient, resource_type: str, resource_id: str, metric_name: str
) -> dict[str, object]:
    response = client.post(
        "/api/detection/resources/evaluate",
        json={
            "resource_type": resource_type,
            "resource_id": resource_id,
            "metric_name": metric_name,
            "value": 92,
            "threshold": 80,
            "timestamp": datetime.now(UTC).isoformat(),
            "correlation_group": "service:checkout",
        },
    )
    assert response.status_code == 200
    return cast(dict[str, object], response.json()["incident"])


def test_api_returns_correlated_incidents_and_shared_diagnosis(client: TestClient) -> None:
    ec2 = create_resource_incident(client, "EC2", "checkout-asg", "CPUUtilization")
    create_resource_incident(client, "DYNAMODB", "checkout-orders", "ReadThrottleEvents")

    response = client.get(f"/api/incidents/{ec2['id']}/correlated")

    assert response.status_code == 200
    incidents = response.json()
    assert len(incidents) == 2
    assert {item["correlation_group"] for item in incidents} == {"service:checkout"}
    assert all(item["diagnosis_confidence"] == pytest.approx(0.72) for item in incidents)
    assert all(len(item["diagnosis_evidence"]) == 2 for item in incidents)


def test_api_exposes_server_side_cost_estimate(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident = create_resource_incident(client, "EC2", "checkout-asg", "CPUUtilization")

    def fake_estimate(runbook_name: str, parameters: dict[str, object]) -> CostEstimateRead:
        assert runbook_name == "scale_ec2_auto_scaling_group"
        assert parameters["desired_capacity"] == 4
        return CostEstimateRead(
            monthly_delta_usd=146,
            currency="USD",
            source="AWS Price List Query API",
            assumptions=["730 hours per month"],
            line_items=[],
        )

    monkeypatch.setattr("apps.api.main._server_cost_estimate", fake_estimate)
    response = client.post(
        f"/api/incidents/{incident['id']}/cost-estimate",
        json={
            "parameters": {
                "auto_scaling_group_name": "checkout-asg",
                "desired_capacity": 4,
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["monthly_delta_usd"] == 146
    assert response.json()["source"] == "AWS Price List Query API"


def test_live_metrics_endpoint_exposes_demo_series_and_audit_markers(client: TestClient) -> None:
    incident = client.post(
        "/api/detection/resources/evaluate",
        json={
            "resource_type": "EC2",
            "resource_id": "api-production-asg",
            "metric_name": "CPUUtilization",
            "value": 91,
            "threshold": 80,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert incident.status_code == 200

    response = client.get("/api/metrics/live?window_minutes=15")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "demo"
    assert len(payload["resources"]) == 3
    ec2 = next(resource for resource in payload["resources"] if resource["resource_type"] == "EC2")
    assert len(ec2["points"]) == 91
    assert any(marker["source"] == "audit" for marker in ec2["markers"])
