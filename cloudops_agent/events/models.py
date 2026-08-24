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
