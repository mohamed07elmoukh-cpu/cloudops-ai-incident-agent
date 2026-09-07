"""Policy-constrained simulated and AWS remediation executors."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloudops_agent.adapters.aws import AwsRemediationAdapter
from cloudops_agent.models import Incident, IncidentStatus, RemediationExecution
from cloudops_agent.remediation.runbooks import RunbookDefinition, RunbookParameter

AWS_RUNBOOKS = {
    "scale_ec2_auto_scaling_group",
    "scale_dynamodb_capacity",
    "scale_rds_storage",
    "scale_rds_compute",
}


class RemediationError(RuntimeError):
    """Base error for rejected remediation attempts."""


class RunbookNotAllowedError(RemediationError):
    pass


class DuplicateRemediationError(RemediationError):
    pass


class InvalidIncidentStateError(RemediationError):
    pass


class ApprovalRequiredError(RemediationError):
    pass


class CostLimitExceededError(RemediationError):
    pass


class RemediationCooldownError(RemediationError):
    pass


class RollbackError(RemediationError):
    pass


class RemediationPolicy:
    """Enforce approvals, cost ceilings, and per-resource cooldowns."""

    def __init__(self, session: Session, global_cost_limit_usd: float | None = None) -> None:
        self.session = session
        configured_limit = os.getenv("REMEDIATION_MAX_MONTHLY_COST_DELTA_USD", "500")
        self.global_cost_limit_usd = (
            global_cost_limit_usd if global_cost_limit_usd is not None else float(configured_limit)
        )

    def validate(
        self,
        incident: Incident,
        runbook: RunbookDefinition,
        *,
        approved_by: str | None,
        estimated_monthly_cost_delta_usd: float | None,
        now: datetime,
    ) -> None:
        if runbook.approval_required and not approved_by:
            raise ApprovalRequiredError(
                f"runbook {runbook.name} requires explicit human approval"
            )
        if runbook.executor == "aws":
            if estimated_monthly_cost_delta_usd is None:
                raise CostLimitExceededError(
                    "estimated_monthly_cost_delta_usd is required for AWS remediation"
                )
            effective_limit = min(
                self.global_cost_limit_usd,
                runbook.max_monthly_cost_delta_usd,
            )
            if estimated_monthly_cost_delta_usd > effective_limit:
                raise CostLimitExceededError(
                    f"estimated monthly cost increase ${estimated_monthly_cost_delta_usd:.2f} "
                    f"exceeds the ${effective_limit:.2f} limit"
                )
        if runbook.cooldown_seconds <= 0:
            return
        cutoff = now - timedelta(seconds=runbook.cooldown_seconds)
        recent = self.session.scalar(
            select(RemediationExecution)
            .join(Incident, RemediationExecution.incident_id == Incident.id)
            .where(
                Incident.source == incident.source,
                RemediationExecution.runbook_name == runbook.name,
                RemediationExecution.started_at >= cutoff,
            )
            .order_by(RemediationExecution.started_at.desc())
            .limit(1)
        )
        if recent is not None:
            raise RemediationCooldownError(
                f"runbook {runbook.name} is in cooldown for resource {incident.source}"
            )


class SimulatedRemediationExecutor:
    """Execute allowlisted runbooks without making external cloud calls."""

    def __init__(
        self,
        session: Session,
        allowed_runbooks: set[str] | None = None,
        policy: RemediationPolicy | None = None,
    ) -> None:
        self.session = session
        self.allowed_runbooks = allowed_runbooks or {"scale_service", *AWS_RUNBOOKS}
        self.policy = policy or RemediationPolicy(session)

    def execute(
        self,
        incident: Incident,
        runbook: RunbookDefinition,
        parameters: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        *,
        approved_by: str | None = None,
        estimated_monthly_cost_delta_usd: float | None = None,
    ) -> RemediationExecution:
        key = self._validate_common(incident, runbook, idempotency_key)
        resolved_parameters = self._resolve_parameters(runbook, parameters or {})
        now = datetime.now(UTC)
        self.policy.validate(
            incident,
            runbook,
            approved_by=approved_by,
            estimated_monthly_cost_delta_usd=estimated_monthly_cost_delta_usd,
            now=now,
        )
        action = runbook.steps[0].action
        incident.status = IncidentStatus.REMEDIATING
        incident.remediation_attempted = True
        execution = RemediationExecution(
            id=uuid.uuid4(),
            incident=incident,
            runbook_name=runbook.name,
            status="VERIFYING",
            started_at=now,
            idempotency_key=key,
            output={
                "simulated": True,
                "action": action,
                "parameters": resolved_parameters,
                "approved_by": approved_by,
                "estimated_monthly_cost_delta_usd": estimated_monthly_cost_delta_usd,
                "verification_policy": runbook.verification.model_dump(),
                "message": "Capacity change simulated; awaiting metric verification.",
            },
        )
        self.session.add(execution)
        self.session.flush()
        incident.status = IncidentStatus.VERIFYING
        self.session.commit()
        self.session.refresh(execution)
        return execution

    def rollback(
        self,
        incident: Incident,
        execution: RemediationExecution,
        runbook: RunbookDefinition,
        *,
        approved_by: str | None = None,
    ) -> RemediationExecution:
        if execution.incident_id != incident.id:
            raise RollbackError("remediation execution does not belong to incident")
        if execution.status == "ROLLED_BACK":
            raise RollbackError("remediation execution is already rolled back")
        if runbook.approval_required and not approved_by:
            raise ApprovalRequiredError(
                f"rollback for {runbook.name} requires explicit human approval"
            )
        output = dict(execution.output)
        output["rollback_result"] = {
            "simulated": True,
            "action": runbook.rollback[0].action,
        }
        output["rollback_approved_by"] = approved_by
        output["rolled_back_at"] = datetime.now(UTC).isoformat()
        execution.output = output
        execution.status = "ROLLED_BACK"
        execution.completed_at = datetime.now(UTC)
        incident.status = IncidentStatus.ESCALATED
        self.session.commit()
        self.session.refresh(execution)
        return execution

    def _validate_common(
        self,
        incident: Incident,
        runbook: RunbookDefinition,
        idempotency_key: str | None,
    ) -> str:
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
        return key

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
            if value is not None:
                SimulatedRemediationExecutor._validate_parameter(name, value, definition)
            resolved[name] = value
        return resolved

    @staticmethod
    def _validate_parameter(name: str, value: Any, definition: RunbookParameter) -> None:
        expected_types: dict[str, tuple[type[Any], ...]] = {
            "string": (str,),
            "integer": (int,),
            "number": (int, float),
            "boolean": (bool,),
        }
        if isinstance(value, bool) and definition.type in {"integer", "number"}:
            raise RemediationError(f"runbook parameter {name} must be {definition.type}")
        if not isinstance(value, expected_types[definition.type]):
            raise RemediationError(f"runbook parameter {name} must be {definition.type}")
        if isinstance(value, int | float) and not isinstance(value, bool):
            if definition.minimum is not None and value < definition.minimum:
                raise RemediationError(
                    f"runbook parameter {name} must be >= {definition.minimum}"
                )
            if definition.maximum is not None and value > definition.maximum:
                raise RemediationError(
                    f"runbook parameter {name} must be <= {definition.maximum}"
                )


class AwsRemediationExecutor(SimulatedRemediationExecutor):
    """Execute allowlisted capacity changes through the AWS SDK adapter."""

    def __init__(
        self,
        session: Session,
        adapter: AwsRemediationAdapter,
        allowed_runbooks: set[str] | None = None,
        policy: RemediationPolicy | None = None,
    ) -> None:
        super().__init__(session, allowed_runbooks or AWS_RUNBOOKS, policy)
        self.adapter = adapter

    def execute(
        self,
        incident: Incident,
        runbook: RunbookDefinition,
        parameters: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        *,
        approved_by: str | None = None,
        estimated_monthly_cost_delta_usd: float | None = None,
    ) -> RemediationExecution:
        if runbook.executor != "aws":
            raise RunbookNotAllowedError(f"runbook {runbook.name} is not an AWS runbook")
        key = self._validate_common(incident, runbook, idempotency_key)
        resolved_parameters = self._resolve_parameters(runbook, parameters or {})
        now = datetime.now(UTC)
        self.policy.validate(
            incident,
            runbook,
            approved_by=approved_by,
            estimated_monthly_cost_delta_usd=estimated_monthly_cost_delta_usd,
            now=now,
        )
        action = runbook.steps[0].action
        incident.status = IncidentStatus.REMEDIATING
        incident.remediation_attempted = True
        execution = RemediationExecution(
            id=uuid.uuid4(),
            incident=incident,
            runbook_name=runbook.name,
            status="RUNNING",
            started_at=now,
            idempotency_key=key,
            output={
                "simulated": False,
                "action": action,
                "parameters": resolved_parameters,
                "approved_by": approved_by,
                "estimated_monthly_cost_delta_usd": estimated_monthly_cost_delta_usd,
                "cost_estimate_source": "AWS Price List Query API",
                "verification_policy": runbook.verification.model_dump(),
            },
        )
        self.session.add(execution)
        self.session.commit()
        try:
            result = self.adapter.execute(action, resolved_parameters)
        except Exception as exc:
            output = dict(execution.output)
            output["error"] = str(exc)
            execution.output = output
            execution.status = "FAILED"
            execution.completed_at = datetime.now(UTC)
            incident.status = IncidentStatus.ESCALATED
            self.session.commit()
            raise RemediationError(f"AWS remediation failed: {exc}") from exc
        output = dict(execution.output)
        output["result"] = result
        execution.output = output
        execution.status = "VERIFYING"
        incident.status = IncidentStatus.VERIFYING
        self.session.commit()
        self.session.refresh(execution)
        return execution

    def rollback(
        self,
        incident: Incident,
        execution: RemediationExecution,
        runbook: RunbookDefinition,
        *,
        approved_by: str | None = None,
    ) -> RemediationExecution:
        if execution.incident_id != incident.id:
            raise RollbackError("remediation execution does not belong to incident")
        if execution.status == "ROLLED_BACK":
            raise RollbackError("remediation execution is already rolled back")
        if runbook.approval_required and not approved_by:
            raise ApprovalRequiredError(
                f"rollback for {runbook.name} requires explicit human approval"
            )
        result = execution.output.get("result", {})
        if not result.get("reversible") or not result.get("rollback"):
            note = result.get("rollback_note", "remediation has no safe automatic rollback")
            raise RollbackError(str(note))
        rollback = result["rollback"]
        try:
            rollback_result = self.adapter.execute(rollback["action"], rollback["arguments"])
        except Exception as exc:
            raise RollbackError(f"AWS rollback failed: {exc}") from exc
        output = dict(execution.output)
        output["rollback_result"] = rollback_result
        output["rollback_approved_by"] = approved_by
        output["rolled_back_at"] = datetime.now(UTC).isoformat()
        execution.output = output
        execution.status = "ROLLED_BACK"
        execution.completed_at = datetime.now(UTC)
        incident.status = IncidentStatus.ESCALATED
        self.session.commit()
        self.session.refresh(execution)
        return execution
