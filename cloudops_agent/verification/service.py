"""Verification of service recovery after remediation."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloudops_agent.models import Evidence, Incident, IncidentStatus, RemediationExecution

RECOVERY_CPU_THRESHOLD = 70.0
MAX_VERIFICATION_FAILURES = 3


class VerificationError(RuntimeError):
    pass


class VerificationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def verify_cpu(
        self, incident: Incident, value: float, timestamp: datetime | None = None
    ) -> Incident:
        if incident.status != IncidentStatus.VERIFYING:
            raise VerificationError(
                f"incident {incident.id} cannot be verified from {incident.status.value}"
            )
        observed_at = timestamp or datetime.now(UTC)
        execution = self.session.scalar(
            select(RemediationExecution)
            .where(RemediationExecution.incident_id == incident.id)
            .order_by(RemediationExecution.started_at.desc())
            .limit(1)
        )
        if execution is None:
            raise VerificationError("incident has no remediation execution")

        incident.evidence.append(
            Evidence(
                incident_id=incident.id,
                metric_name="cpu_usage_percent",
                metric_value=value,
                threshold=RECOVERY_CPU_THRESHOLD,
                timestamp=observed_at,
                raw_data={"phase": "verification", "value": value},
            )
        )
        output = dict(execution.output)
        output["last_verification_cpu_percent"] = value
        if value < RECOVERY_CPU_THRESHOLD:
            execution.status = "SUCCEEDED"
            execution.completed_at = observed_at
            output["verification"] = "passed"
            incident.status = IncidentStatus.RESOLVED
            incident.resolved_at = observed_at
        else:
            incident.verification_failures += 1
            output["verification"] = "failed"
            output["verification_failures"] = incident.verification_failures
            if incident.verification_failures >= MAX_VERIFICATION_FAILURES:
                execution.status = "FAILED"
                execution.completed_at = observed_at
                incident.status = IncidentStatus.ESCALATED
            else:
                incident.status = IncidentStatus.VERIFYING
        execution.output = output
        self.session.commit()
        self.session.refresh(incident)
        return incident

