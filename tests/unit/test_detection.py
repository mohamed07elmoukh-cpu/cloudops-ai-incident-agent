from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloudops_agent.detection import DetectionService
from cloudops_agent.models import Evidence, Incident, IncidentStatus, Severity
from cloudops_agent.schemas import MetricEvaluationRequest


def metric(value: float, source: str = "demo-service") -> MetricEvaluationRequest:
    return MetricEvaluationRequest(
        source=source,
        metric_name="cpu_usage_percent",
        value=value,
        threshold=85,
        timestamp=datetime(2026, 8, 24, 17, tzinfo=UTC),
    )


def test_cpu_below_threshold_creates_no_incident(session: Session) -> None:
    result = DetectionService(session).evaluate(metric(60))

    assert result.anomaly_detected is False
    assert result.incident is None
    assert session.scalar(select(func.count()).select_from(Incident)) == 0


def test_cpu_above_threshold_creates_high_incident_and_evidence(session: Session) -> None:
    result = DetectionService(session).evaluate(metric(92))

    assert result.anomaly_detected is True
    assert result.incident_created is True
    assert result.incident is not None
    assert result.incident.status == IncidentStatus.OPEN
    assert result.incident.severity == Severity.HIGH
    assert result.incident.incident_type == "CPU_SATURATION"
    assert session.scalar(select(func.count()).select_from(Evidence)) == 1


def test_same_correlation_key_does_not_create_duplicate(session: Session) -> None:
    service = DetectionService(session)

    first = service.evaluate(metric(92))
    second = service.evaluate(metric(95))

    assert first.incident is not None
    assert second.incident is not None
    assert second.incident_created is False
    assert first.incident.id == second.incident.id
    assert session.scalar(select(func.count()).select_from(Incident)) == 1
    assert session.scalar(select(func.count()).select_from(Evidence)) == 2

