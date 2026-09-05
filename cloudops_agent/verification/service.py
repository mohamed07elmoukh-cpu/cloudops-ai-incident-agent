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
        return self.verify(incident, "cpu_usage_percent", value, timestamp)

    def verify(
        self,
        incident: Incident,
        metric_name: str,
        value: float,
        timestamp: datetime | None = None,
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

        verification = execution.output.get(
            "verification_policy",
            {
                "metric_name": "cpu_usage_percent",
                "operator": "lt",
                "threshold": RECOVERY_CPU_THRESHOLD,
                "max_attempts": MAX_VERIFICATION_FAILURES,
            },
        )
        expected_metric = str(verification["metric_name"])
        if metric_name != expected_metric:
            raise VerificationError(
                f"runbook expects verification metric {expected_metric}, got {metric_name}"
            )
        threshold = float(verification["threshold"])
        max_attempts = int(verification["max_attempts"])
        passed = _compare(value, str(verification["operator"]), threshold)

        incident.evidence.append(
            Evidence(
                incident_id=incident.id,
                metric_name=metric_name,
                metric_value=value,
                threshold=threshold,
                timestamp=observed_at,
                raw_data={"phase": "verification", "value": value},
            )
        )
        output = dict(execution.output)
        output["last_verification"] = {
            "metric_name": metric_name,
            "value": value,
            "threshold": threshold,
            "passed": passed,
        }
        if metric_name == "cpu_usage_percent":
            output["last_verification_cpu_percent"] = value
        if passed:
            execution.status = "SUCCEEDED"
            execution.completed_at = observed_at
            output["verification"] = "passed"
            incident.status = IncidentStatus.RESOLVED
            incident.resolved_at = observed_at
        else:
            incident.verification_failures += 1
            output["verification"] = "failed"
            output["verification_failures"] = incident.verification_failures
            if incident.verification_failures >= max_attempts:
                execution.status = "FAILED"
                execution.completed_at = observed_at
                incident.status = IncidentStatus.ESCALATED
            else:
                incident.status = IncidentStatus.VERIFYING
        execution.output = output
        self.session.commit()
        self.session.refresh(incident)
        return incident


def _compare(value: float, operator: str, threshold: float) -> bool:
    comparisons = {
        "lt": value < threshold,
        "lte": value <= threshold,
        "gt": value > threshold,
        "gte": value >= threshold,
    }
    try:
        return comparisons[operator]
    except KeyError as exc:
        raise VerificationError(f"unsupported verification operator: {operator}") from exc
