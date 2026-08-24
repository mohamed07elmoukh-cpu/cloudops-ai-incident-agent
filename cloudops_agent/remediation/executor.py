"""Policy-constrained local remediation executor."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloudops_agent.models import Incident, IncidentStatus, RemediationExecution
from cloudops_agent.remediation.runbooks import RunbookDefinition


class RemediationError(RuntimeError):
    """Base error for rejected simulated remediation attempts."""


class RunbookNotAllowedError(RemediationError):
    pass


class DuplicateRemediationError(RemediationError):
    pass


class InvalidIncidentStateError(RemediationError):
    pass


class SimulatedRemediationExecutor:
    """Execute allowlisted runbooks while making no external cloud calls."""

    def __init__(self, session: Session, allowed_runbooks: set[str] | None = None) -> None:
        self.session = session
        self.allowed_runbooks = allowed_runbooks or {"scale_service"}

    def execute(
        self,
        incident: Incident,
        runbook: RunbookDefinition,
        parameters: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> RemediationExecution:
        if runbook.name not in self.allowed_runbooks:
            raise RunbookNotAllowedError(f"runbook is not allowlisted: {runbook.name}")
        if incident.incident_type not in runbook.incident_types:
            raise RunbookNotAllowedError(
                f"runbook {runbook.name} does not support {incident.incident_type}"
            )
        key = idempotency_key or f"{incident.id}:{runbook.name}:{runbook.version}"
        duplicate = self.session.scalar(
            select(RemediationExecution).where(RemediationExecution.idempotency_key == key)
        )
        if duplicate is not None:
            raise DuplicateRemediationError(f"idempotency key already used: {key}")
        if incident.status not in {IncidentStatus.OPEN, IncidentStatus.INVESTIGATING}:
            raise InvalidIncidentStateError(
                f"incident {incident.id} cannot be remediated from {incident.status.value}"
            )

        resolved_parameters = self._resolve_parameters(runbook, parameters or {})
        incident.status = IncidentStatus.REMEDIATING
        incident.remediation_attempted = True
        execution = RemediationExecution(
            id=uuid.uuid4(),
            incident=incident,
            runbook_name=runbook.name,
            status="VERIFYING",
            idempotency_key=key,
            output={
                "simulated": True,
                "action": "scale_service",
                "parameters": resolved_parameters,
                "message": "Service capacity change simulated; awaiting CPU verification.",
            },
        )
        self.session.add(execution)
        self.session.flush()
        incident.status = IncidentStatus.VERIFYING
        self.session.commit()
        self.session.refresh(execution)
        return execution

    @staticmethod
    def _resolve_parameters(
        runbook: RunbookDefinition, supplied: dict[str, Any]
    ) -> dict[str, Any]:
        unknown = set(supplied) - set(runbook.parameters)
        if unknown:
            raise RemediationError(f"unknown runbook parameters: {sorted(unknown)}")
        resolved: dict[str, Any] = {}
        for name, definition in runbook.parameters.items():
            value = supplied.get(name, definition.default)
            if definition.required and value is None:
                raise RemediationError(f"missing required runbook parameter: {name}")
            resolved[name] = value
        return resolved
