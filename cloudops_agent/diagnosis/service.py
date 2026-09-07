"""Deterministic, evidence-backed diagnosis for correlated AWS incidents."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from cloudops_agent.models import Incident, IncidentStatus

ACTIVE_STATUSES = {
    IncidentStatus.OPEN,
    IncidentStatus.INVESTIGATING,
    IncidentStatus.REMEDIATING,
    IncidentStatus.VERIFYING,
}


class DiagnosticService:
    """Refresh a conservative diagnosis shared by one application group."""

    def __init__(self, session: Session, correlation_window_minutes: int = 30) -> None:
        self.session = session
        self.window = timedelta(minutes=correlation_window_minutes)

    def refresh(self, correlation_group: str, *, commit: bool = True) -> list[Incident]:
        incidents = list(
            self.session.scalars(
                select(Incident)
                .options(selectinload(Incident.evidence))
                .where(
                    Incident.correlation_group == correlation_group,
                    Incident.status.in_(ACTIVE_STATUSES),
                    Incident.detected_at >= datetime.now(UTC) - self.window,
                )
                .order_by(Incident.detected_at)
            ).unique()
        )
        if not incidents:
            return []

        types = {incident.incident_type for incident in incidents}
        services = {incident_type.split("_", maxsplit=1)[0] for incident_type in types}
        evidence = self._evidence_snapshot(incidents)
        root_cause, summary = self._diagnose(types, len(services))
        confidence = min(0.55 + max(0, len(services) - 1) * 0.17, 0.89)
        diagnosed_at = datetime.now(UTC)
        for incident in incidents:
            incident.diagnosis_summary = summary
            incident.probable_root_cause = root_cause
            incident.diagnosis_confidence = confidence
            incident.diagnosis_evidence = evidence
            incident.diagnosed_at = diagnosed_at
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return incidents

    @staticmethod
    def _evidence_snapshot(incidents: list[Incident]) -> list[dict[str, Any]]:
        snapshot: list[dict[str, Any]] = []
        for incident in incidents:
            for item in incident.evidence:
                snapshot.append(
                    {
                        "incident_id": str(incident.id),
                        "resource": incident.source,
                        "incident_type": incident.incident_type,
                        "metric": item.metric_name,
                        "value": item.metric_value,
                        "threshold": item.threshold,
                        "observed_at": item.timestamp.isoformat(),
                    }
                )
        return snapshot[-20:]

    @staticmethod
    def _diagnose(types: set[str], service_count: int) -> tuple[str, str]:
        if "RDS_STORAGE_LOW" in types:
            cause = "RDS storage pressure is the strongest currently observed bottleneck."
        elif "DYNAMODB_CAPACITY_SATURATION" in types and "EC2_CAPACITY_SATURATION" in types:
            cause = "DynamoDB throttling is likely amplifying load and saturation on EC2."
        elif "RDS_COMPUTE_SATURATION" in types and "EC2_CAPACITY_SATURATION" in types:
            cause = "RDS compute saturation is a likely downstream bottleneck for EC2 traffic."
        elif "DYNAMODB_CAPACITY_SATURATION" in types:
            cause = "Provisioned DynamoDB throughput is the strongest observed constraint."
        elif "RDS_COMPUTE_SATURATION" in types:
            cause = "RDS compute capacity is the strongest observed constraint."
        else:
            cause = "EC2 compute capacity is the strongest observed constraint."
        summary = (
            f"Correlated {service_count} AWS service signal(s). "
            "The conclusion is rule-based and limited to the attached metric evidence."
        )
        return cause, summary
