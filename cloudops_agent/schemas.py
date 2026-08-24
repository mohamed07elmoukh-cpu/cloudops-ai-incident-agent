"""Validated API input and output schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cloudops_agent.models import IncidentStatus, Severity


class MetricEvaluationRequest(BaseModel):
    source: str = Field(min_length=1, max_length=255)
    metric_name: str = Field(pattern=r"^cpu_usage_percent$")
    value: float = Field(ge=0, le=100)
    threshold: float = Field(ge=0, le=100)
    timestamp: datetime


class VerificationRequest(BaseModel):
    value: float = Field(ge=0, le=100)
    metric_name: str = Field(default="cpu_usage_percent", pattern=r"^cpu_usage_percent$")
    timestamp: datetime | None = None


class RemediationRequest(BaseModel):
    runbook_name: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)
    parameters: dict[str, Any] = Field(default_factory=dict)


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    incident_id: uuid.UUID
    metric_name: str
    metric_value: float
    threshold: float
    timestamp: datetime
    raw_data: dict[str, Any]


class RemediationExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    incident_id: uuid.UUID
    runbook_name: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    output: dict[str, Any]
    idempotency_key: str


class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    incident_type: str
    severity: Severity
    status: IncidentStatus
    title: str
    description: str
    detected_at: datetime
    resolved_at: datetime | None
    correlation_key: str
    remediation_attempted: bool
    verification_failures: int
    evidence: list[EvidenceRead] = Field(default_factory=list)
    remediation_executions: list[RemediationExecutionRead] = Field(default_factory=list)


class DetectionEvaluationResponse(BaseModel):
    anomaly_detected: bool
    incident_created: bool
    incident: IncidentRead | None = None

