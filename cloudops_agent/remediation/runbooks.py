"""Strict loading and validation of declarative remediation runbooks."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class InvalidRunbookError(ValueError):
    """Raised when a runbook cannot be parsed or does not match the schema."""


class RunbookParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["string", "integer", "number", "boolean"]
    required: bool = True
    default: Any | None = None
    minimum: float | None = None
    maximum: float | None = None


class RunbookStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1)
    description: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class RunbookVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_name: str = Field(min_length=1)
    operator: Literal["lt", "lte", "gt", "gte"]
    threshold: float
    max_attempts: int = Field(ge=1, le=10)


class RunbookDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(min_length=1)
    incident_types: list[str] = Field(min_length=1)
    executor: Literal["simulated", "aws"] = "simulated"
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    approval_required: bool = False
    max_monthly_cost_delta_usd: float = Field(default=0, ge=0)
    cooldown_seconds: int = Field(default=0, ge=0, le=86400)
    parameters: dict[str, RunbookParameter]
    preconditions: list[str] = Field(min_length=1)
    steps: list[RunbookStep] = Field(min_length=1)
    verification: RunbookVerification
    rollback: list[RunbookStep] = Field(min_length=1)

    @field_validator("incident_types")
    @classmethod
    def unique_incident_types(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("incident_types must not contain duplicates")
        return value


class RunbookLoader:
    """Load runbooks from a fixed directory without allowing path traversal."""

    def __init__(self, runbook_directory: Path | None = None) -> None:
        self.runbook_directory = (
            runbook_directory or Path(__file__).resolve().parents[2] / "runbooks"
        ).resolve()

    def load(self, name: str) -> RunbookDefinition:
        if not name or Path(name).name != name:
            raise InvalidRunbookError("runbook name must be a simple file stem")
        path = (self.runbook_directory / f"{name}.yaml").resolve()
        if path.parent != self.runbook_directory or not path.is_file():
            raise InvalidRunbookError(f"runbook not found: {name}")
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise InvalidRunbookError("runbook root must be a mapping")
            runbook = RunbookDefinition.model_validate(raw)
        except (OSError, yaml.YAMLError, ValidationError) as exc:
            raise InvalidRunbookError(f"invalid runbook {name}: {exc}") from exc
        if runbook.name != name:
            raise InvalidRunbookError("runbook name must match its file name")
        return runbook

    def find_for_incident(self, incident_type: str) -> RunbookDefinition:
        for path in sorted(self.runbook_directory.glob("*.yaml")):
            try:
                runbook = self.load(path.stem)
            except InvalidRunbookError:
                continue
            if incident_type in runbook.incident_types:
                return runbook
        raise InvalidRunbookError(f"no valid runbook supports {incident_type}")
