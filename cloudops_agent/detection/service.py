"""CPU anomaly detection and incident correlation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloudops_agent.models import Evidence, Incident, IncidentStatus, Severity
from cloudops_agent.schemas import MetricEvaluationRequest

CPU_INCIDENT_TYPE = "CPU_SATURATION"
ACTIVE_INCIDENT_STATUSES = (
    IncidentStatus.OPEN,
    IncidentStatus.INVESTIGATING,
    IncidentStatus.REMEDIATING,
    IncidentStatus.VERIFYING,
)


@dataclass(frozen=True)
class DetectionResult:
    anomaly_detected: bool
    incident_created: bool
    incident: Incident | None


class DetectionService:
    """Turn a CPU threshold breach into one correlated incident."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def evaluate(
        self,
        metric: MetricEvaluationRequest,
        *,
        correlation_key: str | None = None,
        raw_data: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> DetectionResult:
        if metric.value <= metric.threshold:
            return DetectionResult(False, False, None)

        effective_correlation_key = correlation_key or cpu_correlation_key(metric.source)
        incident = self.session.scalar(
            select(Incident).where(
                Incident.correlation_key == effective_correlation_key,
                Incident.status.in_(ACTIVE_INCIDENT_STATUSES),
            )
        )
        created = incident is None
        if incident is None:
            incident = Incident(
                source=metric.source,
                incident_type=CPU_INCIDENT_TYPE,
                severity=Severity.HIGH,
                status=IncidentStatus.OPEN,
                title=f"CPU saturation detected on {metric.source}",
                description=(
                    f"CPU usage reached {metric.value:.1f}% and exceeded "
                    f"the configured threshold of {metric.threshold:.1f}%."
                ),
                detected_at=metric.timestamp,
                correlation_key=effective_correlation_key,
                remediation_attempted=False,
            )
            self.session.add(incident)
            self.session.flush()

        incident.evidence.append(
            Evidence(
                incident_id=incident.id,
                metric_name=metric.metric_name,
                metric_value=metric.value,
                threshold=metric.threshold,
                timestamp=metric.timestamp,
                raw_data=raw_data or metric.model_dump(mode="json"),
            )
        )
        if commit:
            self.session.commit()
            self.session.refresh(incident)
        else:
            self.session.flush()
        return DetectionResult(True, created, incident)


def cpu_correlation_key(source: str) -> str:
    return f"{source}:cpu-saturation"
