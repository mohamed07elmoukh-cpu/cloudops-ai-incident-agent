from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from cloudops_agent.impact import BusinessImpactService
from cloudops_agent.models import Evidence, Incident, IncidentStatus, Severity


def add_incident(
    session: Session,
    *,
    source: str,
    incident_type: str,
    detected_at: datetime,
    resolved_at: datetime | None = None,
    status: IncidentStatus = IncidentStatus.OPEN,
) -> Incident:
    incident = Incident(
        source=source,
        incident_type=incident_type,
        severity=Severity.HIGH,
        status=status,
        title="Capacity incident",
        description="Capacity threshold breached",
        detected_at=detected_at,
        resolved_at=resolved_at,
        correlation_key=f"{source}:{incident_type}:{detected_at.isoformat()}",
        correlation_group="service:checkout",
    )
    session.add(incident)
    session.flush()
    return incident


def test_calculates_slo_without_double_counting_correlated_outages(session: Session) -> None:
    now = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    add_incident(
        session,
        source="checkout-asg",
        incident_type="EC2_CAPACITY_SATURATION",
        detected_at=now - timedelta(minutes=20),
        resolved_at=now - timedelta(minutes=10),
        status=IncidentStatus.RESOLVED,
    )
    add_incident(
        session,
        source="orders-db",
        incident_type="RDS_COMPUTE_SATURATION",
        detected_at=now - timedelta(minutes=18),
        resolved_at=now - timedelta(minutes=8),
        status=IncidentStatus.RESOLVED,
    )

    assessment = (
        BusinessImpactService().overview(list(session.query(Incident)), now=now).services[0]
    )

    assert assessment.service_name == "Commandes"
    assert assessment.error_budget_total_minutes == pytest.approx(43.2)
    assert assessment.error_budget_consumed_minutes == 12.0
    assert assessment.availability_percent == pytest.approx(99.97222)
    assert assessment.error_budget_remaining_minutes == pytest.approx(31.2)
    assert assessment.transactions_at_risk_per_minute == 0


def test_exposes_business_risk_and_observed_time_to_saturation(session: Session) -> None:
    now = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    incident = add_incident(
        session,
        source="orders-db",
        incident_type="RDS_STORAGE_LOW",
        detected_at=now - timedelta(minutes=10),
    )
    incident.evidence.extend(
        [
            Evidence(
                incident_id=incident.id,
                metric_name="FreeStorageSpace",
                metric_value=8,
                threshold=10,
                timestamp=now - timedelta(minutes=10),
                raw_data={"condition": "below"},
            ),
            Evidence(
                incident_id=incident.id,
                metric_name="FreeStorageSpace",
                metric_value=4,
                threshold=10,
                timestamp=now,
                raw_data={"condition": "below"},
            ),
        ]
    )
    session.flush()

    assessment = BusinessImpactService().assess_incident(
        incident, list(session.query(Incident)), now=now
    )

    assert assessment.transactions_at_risk_per_minute == 240
    assert assessment.time_to_saturation_minutes == 10.0
    assert assessment.saturation_method == "observed_trend"
    assert assessment.status == "at_risk"
    assert "240 transactions/minute" in assessment.summary


def test_marks_the_slo_error_budget_as_exhausted(session: Session) -> None:
    now = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    incident = add_incident(
        session,
        source="checkout-asg",
        incident_type="EC2_CAPACITY_SATURATION",
        detected_at=now - timedelta(minutes=60),
    )

    assessment = BusinessImpactService().assess_incident(
        incident, list(session.query(Incident)), now=now
    )

    assert assessment.error_budget_remaining_minutes == 0
    assert assessment.error_budget_remaining_percent == 0
    assert assessment.error_budget_burn_rate == pytest.approx(1.39)
    assert assessment.status == "exhausted"
    assert "budget d'erreur SLO est épuisé" in assessment.summary
