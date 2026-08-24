from datetime import UTC, datetime

from sqlalchemy.orm import Session

from cloudops_agent.detection import DetectionService
from cloudops_agent.models import Incident, IncidentStatus
from cloudops_agent.remediation.executor import SimulatedRemediationExecutor
from cloudops_agent.remediation.runbooks import RunbookLoader
from cloudops_agent.schemas import MetricEvaluationRequest
from cloudops_agent.verification import VerificationService


def remediated_incident(session: Session) -> Incident:
    result = DetectionService(session).evaluate(
        MetricEvaluationRequest(
            source="demo-service",
            metric_name="cpu_usage_percent",
            value=92,
            threshold=85,
            timestamp=datetime.now(UTC),
        )
    )
    assert result.incident is not None
    SimulatedRemediationExecutor(session).execute(
        result.incident, RunbookLoader().load("scale_service")
    )
    return result.incident


def test_cpu_below_70_resolves_incident(session: Session) -> None:
    incident = remediated_incident(session)

    VerificationService(session).verify_cpu(incident, 55)

    assert incident.status == IncidentStatus.RESOLVED
    assert incident.resolved_at is not None
    assert incident.remediation_executions[-1].status == "SUCCEEDED"


def test_three_failed_verifications_escalate_incident(session: Session) -> None:
    incident = remediated_incident(session)
    verifier = VerificationService(session)

    verifier.verify_cpu(incident, 90)
    verifier.verify_cpu(incident, 85)
    verifier.verify_cpu(incident, 75)

    assert incident.verification_failures == 3
    assert incident.status == IncidentStatus.ESCALATED
    assert incident.remediation_executions[-1].status == "FAILED"

