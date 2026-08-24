"""Alertmanager webhook validation and CloudEvent normalization."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from cloudops_agent.detection.service import cpu_correlation_key
from cloudops_agent.events.models import CloudEventEnvelope, MetricThresholdPayload
from cloudops_agent.models import Severity

EVENT_NAMESPACE = uuid.UUID("c94ea40c-35bc-4fc6-ae80-30b63ad92ca6")


class AlertmanagerAlert(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: str = Field(pattern=r"^(firing|resolved)$")
    labels: dict[str, str]
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    generator_url: str = Field(default="", alias="generatorURL")
    fingerprint: str = ""


class AlertmanagerWebhook(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    receiver: str
    status: str = Field(pattern=r"^(firing|resolved)$")
    alerts: list[AlertmanagerAlert] = Field(min_length=1)
    group_labels: dict[str, str] = Field(default_factory=dict, alias="groupLabels")
    common_labels: dict[str, str] = Field(default_factory=dict, alias="commonLabels")
    common_annotations: dict[str, str] = Field(default_factory=dict, alias="commonAnnotations")
    external_url: str = Field(default="", alias="externalURL")
    version: str = "4"
    group_key: str = Field(default="", alias="groupKey")
    truncated_alerts: int = Field(default=0, alias="truncatedAlerts", ge=0)


def _stable_alert_fingerprint(alert: AlertmanagerAlert) -> str:
    if alert.fingerprint:
        return alert.fingerprint
    canonical = json.dumps(
        {
            "labels": alert.labels,
            "starts_at": alert.starts_at.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _parse_number(value: str, field_name: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"Alertmanager {field_name} must be numeric") from exc


def alertmanager_to_cloud_events(webhook: AlertmanagerWebhook) -> list[CloudEventEnvelope]:
    """Normalize every Alertmanager alert using deterministic identifiers."""
    trace_seed = webhook.group_key or json.dumps(webhook.group_labels, sort_keys=True)
    trace_id = uuid.uuid5(EVENT_NAMESPACE, f"alertmanager-trace:{trace_seed}")
    events: list[CloudEventEnvelope] = []
    for alert in webhook.alerts:
        source = alert.labels.get("service", webhook.common_labels.get("service", "unknown"))
        severity_text = alert.labels.get("severity", "high").upper()
        try:
            severity = Severity(severity_text)
        except ValueError as exc:
            raise ValueError(f"unsupported Alertmanager severity: {severity_text}") from exc
        fingerprint = _stable_alert_fingerprint(alert)
        # Alertmanager fingerprints identify a label set, not one alert occurrence.
        # Include startsAt so retries of one notification stay idempotent while a
        # later recurrence of the same alert can produce a new domain event.
        occurrence = alert.starts_at.isoformat()
        event_id = uuid.uuid5(
            EVENT_NAMESPACE,
            f"alertmanager:{fingerprint}:{alert.status}:{occurrence}",
        )
        threshold_text = alert.labels.get("threshold", "85")
        value_text = alert.annotations.get("current_value", threshold_text)
        payload = MetricThresholdPayload(
            metric_name=alert.labels.get("metric_name", "demo_cpu_load_percent"),
            value=_parse_number(value_text, "current_value"),
            threshold=_parse_number(threshold_text, "threshold"),
            alert_status=alert.status,
            labels=alert.labels,
            annotations=alert.annotations,
        )
        event_type = (
            "METRIC_THRESHOLD_BREACHED"
            if alert.status == "firing"
            else "METRIC_THRESHOLD_RECOVERED"
        )
        events.append(
            CloudEventEnvelope(
                event_id=event_id,
                event_type=event_type,
                source=source,
                occurred_at=alert.starts_at,
                severity=severity,
                correlation_key=cpu_correlation_key(source),
                payload=payload.model_dump(mode="json"),
                schema_version="1.0",
                trace_id=trace_id,
            )
        )
    return events
