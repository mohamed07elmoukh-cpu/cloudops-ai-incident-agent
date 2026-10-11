"""Validated API input and output schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from cloudops_agent.models import IncidentStatus, Severity


class MetricEvaluationRequest(BaseModel):
    source: str = Field(min_length=1, max_length=255)
    metric_name: str = Field(pattern=r"^cpu_usage_percent$")
    value: float = Field(ge=0, le=100)
    threshold: float = Field(ge=0, le=100)
    timestamp: datetime


class VerificationRequest(BaseModel):
    value: float
    metric_name: str = Field(default="cpu_usage_percent", min_length=1, max_length=255)
    timestamp: datetime | None = None


class RemediationRequest(BaseModel):
    runbook_name: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)
    parameters: dict[str, Any] = Field(default_factory=dict)
    approved_by: str | None = Field(default=None, min_length=1, max_length=255)
    estimated_monthly_cost_delta_usd: float | None = Field(default=None, ge=0)


class CostEstimateRead(BaseModel):
    monthly_delta_usd: float = Field(ge=0)
    currency: str
    source: str
    assumptions: list[str]
    line_items: list[dict[str, Any]]


class RollbackRequest(BaseModel):
    execution_id: uuid.UUID
    approved_by: str | None = Field(default=None, min_length=1, max_length=255)


class ResourceMetricEvaluationRequest(BaseModel):
    resource_type: Literal["EC2", "DYNAMODB", "RDS"]
    resource_id: str = Field(min_length=1, max_length=255)
    metric_name: str = Field(min_length=1, max_length=255)
    value: float
    threshold: float
    condition: Literal["above", "below"] = "above"
    timestamp: datetime
    severity: Severity = Severity.HIGH
    correlation_group: str | None = Field(default=None, min_length=1, max_length=255)


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

    id: uuid.UUID
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
    correlation_group: str | None
    diagnosis_summary: str | None
    probable_root_cause: str | None
    diagnosis_confidence: float | None
    diagnosis_evidence: list[dict[str, Any]]
    diagnosed_at: datetime | None
    remediation_attempted: bool
    verification_failures: int
    evidence: list[EvidenceRead] = Field(default_factory=list)
    remediation_executions: list[RemediationExecutionRead] = Field(default_factory=list)


class DetectionEvaluationResponse(BaseModel):
    anomaly_detected: bool
    incident_created: bool
    incident: IncidentRead | None = None


class ProcessedEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: uuid.UUID
    event_type: str
    processed_at: datetime
    incident_id: uuid.UUID | None
    status: str
    trace_id: uuid.UUID
    published_at: datetime | None = None
    message_id: str | None = None


class TimelineEntry(BaseModel):
    timestamp: datetime
    kind: str
    title: str
    status: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class DailyIncidentPoint(BaseModel):
    date: str
    detected: int
    resolved: int


class IncidentStatistics(BaseModel):
    total: int
    open: int
    resolved: int
    escalated: int
    active: int
    average_resolution_seconds: float | None
    by_status: dict[str, int]
    by_severity: dict[str, int]
    daily_trend: list[DailyIncidentPoint]


class BusinessImpactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    service_key: str
    service_name: str
    criticality: Literal["standard", "high", "critical"]
    transactions_per_minute: float = Field(ge=0)
    transactions_at_risk_per_minute: float = Field(ge=0)
    slo_target_percent: float = Field(gt=0, le=100)
    slo_window_days: int = Field(gt=0)
    window_started_at: datetime
    assessed_at: datetime
    availability_percent: float = Field(ge=0, le=100)
    error_budget_total_minutes: float = Field(ge=0)
    error_budget_consumed_minutes: float = Field(ge=0)
    error_budget_remaining_minutes: float = Field(ge=0)
    error_budget_remaining_percent: float = Field(ge=0, le=100)
    error_budget_burn_rate: float = Field(ge=0)
    status: Literal["healthy", "at_risk", "exhausted"]
    active_incidents: int = Field(ge=0)
    affected_resources: list[str]
    time_to_saturation_minutes: float | None = Field(default=None, ge=0)
    saturation_metric: str | None
    saturation_method: Literal["observed_trend", "conservative_projection", "unavailable"]
    summary: str
    assumptions: list[str]


class BusinessImpactOverviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    assessed_at: datetime
    total_transactions_at_risk_per_minute: float = Field(ge=0)
    services_at_risk: int = Field(ge=0)
    services: list[BusinessImpactRead]


class LiveMetricSeries(BaseModel):
    key: str
    label: str
    unit: str
    color: str


class LiveMetricPoint(BaseModel):
    timestamp: datetime
    values: dict[str, float]


class LiveMetricMarker(BaseModel):
    timestamp: datetime
    kind: Literal["detection", "remediation", "rollback"]
    label: str
    incident_id: uuid.UUID | None = None
    source: Literal["audit", "demo"]


class LiveResourceMetrics(BaseModel):
    resource_type: Literal["EC2", "DYNAMODB", "RDS"]
    resource_id: str
    title: str
    subtitle: str
    status: Literal["healthy", "attention"]
    metadata: dict[str, str]
    series: list[LiveMetricSeries]
    points: list[LiveMetricPoint]
    markers: list[LiveMetricMarker]


class LiveMetricsRead(BaseModel):
    mode: Literal["aws", "demo"]
    region: str
    generated_at: datetime
    window_minutes: int
    period_seconds: int
    refresh_seconds: int
    resources: list[LiveResourceMetrics]


class SystemComponentHealth(BaseModel):
    status: str
    detail: str | None = None
    visible_messages: int | None = None
    in_flight_messages: int | None = None


class SystemHealthRead(BaseModel):
    status: str
    checked_at: datetime
    components: dict[str, SystemComponentHealth]
