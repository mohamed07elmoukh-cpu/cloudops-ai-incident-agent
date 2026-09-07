"""Strict normalized event contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from cloudops_agent.models import Severity

SUPPORTED_SCHEMA_VERSION: Literal["1.0"] = "1.0"


class CloudEventEnvelope(BaseModel):
    """Versioned event crossing the webhook-to-worker boundary."""

    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: uuid.UUID
    event_type: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=255)
    occurred_at: datetime
    severity: Severity
    correlation_key: str = Field(min_length=1, max_length=255)
    payload: dict[str, Any]
    schema_version: Literal["1.0"] = SUPPORTED_SCHEMA_VERSION
    trace_id: uuid.UUID


class MetricThresholdPayload(BaseModel):
    """Validated business payload consumed by the CPU detection adapter."""

    model_config = ConfigDict(extra="forbid")

    metric_name: str = Field(min_length=1, max_length=255)
    value: float = Field(ge=0, le=100)
    threshold: float = Field(ge=0, le=100)
    alert_status: Literal["firing", "resolved"]
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)


class AwsResourceMetricPayload(BaseModel):
    """Normalized capacity signal originating from a CloudWatch alarm."""

    model_config = ConfigDict(extra="forbid")

    resource_type: Literal["EC2", "DYNAMODB", "RDS"]
    resource_id: str = Field(min_length=1, max_length=255)
    metric_name: str = Field(min_length=1, max_length=255)
    value: float
    threshold: float
    condition: Literal["above", "below"]
    alarm_name: str = Field(min_length=1, max_length=255)
    aws_account_id: str = Field(min_length=1, max_length=32)
    aws_region: str = Field(min_length=1, max_length=64)
    dimensions: dict[str, str] = Field(default_factory=dict)
    correlation_group: str = Field(min_length=1, max_length=255)
    raw_event: dict[str, Any]
