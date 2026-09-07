"""CPU anomaly detection and incident correlation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloudops_agent.diagnosis import DiagnosticService
from cloudops_agent.models import Evidence, Incident, IncidentStatus, Severity
from cloudops_agent.schemas import MetricEvaluationRequest, ResourceMetricEvaluationRequest

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

    def evaluate_resource(
        self,
        metric: ResourceMetricEvaluationRequest,
        *,
        raw_data: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> DetectionResult:
        """Turn an EC2, DynamoDB, or RDS capacity breach into an incident."""
        breached = (
            metric.value > metric.threshold
            if metric.condition == "above"
            else metric.value < metric.threshold
        )
        if not breached:
            return DetectionResult(False, False, None)

        incident_type = resource_incident_type(metric.resource_type, metric.metric_name)
        correlation_key = (
            f"{metric.resource_type.lower()}:{metric.resource_id}:{incident_type.lower()}"
        )
        incident = self.session.scalar(
            select(Incident).where(
                Incident.correlation_key == correlation_key,
                Incident.status.in_(ACTIVE_INCIDENT_STATUSES),
            )
        )
        created = incident is None
        if incident is None:
            comparison = "exceeded" if metric.condition == "above" else "fell below"
            incident = Incident(
                source=metric.resource_id,
                incident_type=incident_type,
                severity=metric.severity,
                status=IncidentStatus.OPEN,
                title=f"{metric.resource_type} capacity incident on {metric.resource_id}",
                description=(
                    f"{metric.metric_name} reached {metric.value} and {comparison} "
                    f"the configured threshold of {metric.threshold}."
                ),
                detected_at=metric.timestamp,
                correlation_key=correlation_key,
                correlation_group=metric.correlation_group,
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
        if metric.correlation_group:
            DiagnosticService(self.session).refresh(metric.correlation_group, commit=False)
        if commit:
            self.session.commit()
            self.session.refresh(incident)
        else:
            self.session.flush()
        return DetectionResult(True, created, incident)


def cpu_correlation_key(source: str) -> str:
    return f"{source}:cpu-saturation"


def resource_incident_type(resource_type: str, metric_name: str) -> str:
    """Map AWS capacity signals to the runbook-specific incident type."""
    if resource_type == "EC2":
        return "EC2_CAPACITY_SATURATION"
    if resource_type == "DYNAMODB":
        return "DYNAMODB_CAPACITY_SATURATION"
    if metric_name.lower() in {"freestoragespace", "free_storage_space"}:
        return "RDS_STORAGE_LOW"
    return "RDS_COMPUTE_SATURATION"
