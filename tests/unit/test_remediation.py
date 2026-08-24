from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from cloudops_agent.detection import DetectionService
from cloudops_agent.models import IncidentStatus
from cloudops_agent.remediation.executor import (
    DuplicateRemediationError,
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

