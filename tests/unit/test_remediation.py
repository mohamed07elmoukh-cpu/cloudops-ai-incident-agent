from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from cloudops_agent.detection import DetectionService
from cloudops_agent.models import Incident, IncidentStatus, Severity
from cloudops_agent.remediation.executor import (
    ApprovalRequiredError,
    CostLimitExceededError,
    DuplicateRemediationError,
    RemediationCooldownError,
    RunbookNotAllowedError,
    SimulatedRemediationExecutor,
)
from cloudops_agent.remediation.runbooks import RunbookLoader
from cloudops_agent.schemas import MetricEvaluationRequest


def incident_from_detection(session: Session):  # type: ignore[no-untyped-def]
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
    return result.incident


def test_non_allowlisted_runbook_is_rejected(session: Session) -> None:
    incident = incident_from_detection(session)
    runbook = RunbookLoader().load("scale_service").model_copy(update={"name": "unsafe_scale"})

    with pytest.raises(RunbookNotAllowedError):
        SimulatedRemediationExecutor(session).execute(incident, runbook)


def test_duplicate_remediation_is_rejected(session: Session) -> None:
    incident = incident_from_detection(session)
    runbook = RunbookLoader().load("scale_service")
    executor = SimulatedRemediationExecutor(session)

    execution = executor.execute(incident, runbook, idempotency_key="same-operation")

    assert incident.status == IncidentStatus.VERIFYING
    assert execution.output["simulated"] is True
    with pytest.raises(DuplicateRemediationError):
        executor.execute(incident, runbook, idempotency_key="same-operation")


def aws_incident(session: Session, incident_type: str, source: str = "resource-1") -> Incident:
    incident = Incident(
        source=source,
        incident_type=incident_type,
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        title="Capacity saturation",
        description="Capacity threshold breached",
        detected_at=datetime.now(UTC),
        correlation_key=f"{source}:{incident_type}:{datetime.now(UTC).timestamp()}",
    )
    session.add(incident)
    session.commit()
    return incident


def test_rds_compute_requires_approval_and_enforces_cost_limit(session: Session) -> None:
    incident = aws_incident(session, "RDS_COMPUTE_SATURATION", "orders-db")
    runbook = RunbookLoader().load("scale_rds_compute")
    executor = SimulatedRemediationExecutor(session)
    parameters = {
        "db_instance_identifier": "orders-db",
        "db_instance_class": "db.t3.large",
        "apply_immediately": False,
    }

    with pytest.raises(ApprovalRequiredError):
        executor.execute(
            incident,
            runbook,
            parameters,
            estimated_monthly_cost_delta_usd=100,
        )
    with pytest.raises(CostLimitExceededError):
        executor.execute(
            incident,
            runbook,
            parameters,
            approved_by="ops@example.com",
            estimated_monthly_cost_delta_usd=501,
        )


def test_cooldown_prevents_repeated_scaling_of_same_resource(session: Session) -> None:
    runbook = RunbookLoader().load("scale_ec2_auto_scaling_group")
    executor = SimulatedRemediationExecutor(session)
    parameters = {"auto_scaling_group_name": "api-asg", "desired_capacity": 4}
    first = aws_incident(session, "EC2_CAPACITY_SATURATION", "api-asg")
    executor.execute(first, runbook, parameters, estimated_monthly_cost_delta_usd=50)
    second = aws_incident(session, "EC2_CAPACITY_SATURATION", "api-asg")

    with pytest.raises(RemediationCooldownError):
        executor.execute(second, runbook, parameters, estimated_monthly_cost_delta_usd=50)
