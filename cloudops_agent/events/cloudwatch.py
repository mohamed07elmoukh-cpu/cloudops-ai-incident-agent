"""Normalize native CloudWatch alarm events delivered by EventBridge."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from cloudops_agent.events.models import AwsResourceMetricPayload, CloudEventEnvelope
from cloudops_agent.models import Severity

EVENT_NAMESPACE = uuid.UUID("d70b9291-b238-4cc1-a231-50a30c9bec86")
EVENT_TYPE = "AWS_RESOURCE_THRESHOLD_BREACHED"


class AlarmState(BaseModel):
    model_config = ConfigDict(extra="allow")

    value: str
    reason: str = ""
    reason_data: str | dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("reasonData", "reason_data"),
    )


class AlarmDetail(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    alarm_name: str = Field(alias="alarmName", min_length=1)
    state: AlarmState
    configuration: dict[str, Any] = Field(default_factory=dict)


class CloudWatchAlarmEvent(BaseModel):
    """Relevant subset of an EventBridge CloudWatch alarm event."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    version: str
    event_id: str = Field(alias="id", min_length=1)
    detail_type: Literal["CloudWatch Alarm State Change"] = Field(alias="detail-type")
    source: Literal["aws.cloudwatch"]
    account: str = Field(min_length=1)
    time: datetime
    region: str = Field(min_length=1)
    resources: list[str] = Field(min_length=1)
    detail: AlarmDetail


def _reason_data(state: AlarmState) -> dict[str, Any]:
    if isinstance(state.reason_data, dict):
        return state.reason_data
    if not state.reason_data:
        return {}
    try:
        parsed = json.loads(state.reason_data)
    except json.JSONDecodeError as exc:
        raise ValueError("CloudWatch alarm reasonData is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("CloudWatch alarm reasonData must be a JSON object")
    return parsed


def _metric_configuration(configuration: dict[str, Any]) -> dict[str, Any]:
    metrics = configuration.get("metrics", [])
    if not isinstance(metrics, list):
        raise ValueError("CloudWatch alarm configuration.metrics must be a list")
    for query in metrics:
        if not isinstance(query, dict):
            continue
        metric_stat = query.get("metricStat")
        if not isinstance(metric_stat, dict):
            continue
        metric = metric_stat.get("metric")
        if isinstance(metric, dict) and metric.get("namespace") in {
            "AWS/EC2",
            "AWS/DynamoDB",
            "AWS/RDS",
        }:
            return metric
    raise ValueError("CloudWatch alarm has no supported EC2, DynamoDB, or RDS metric")


def _latest_value(reason_data: dict[str, Any]) -> float:
    evaluated = reason_data.get("evaluatedDatapoints")
    if isinstance(evaluated, list) and evaluated:
        latest = evaluated[-1]
        if isinstance(latest, dict) and "value" in latest:
            return float(latest["value"])
        if isinstance(latest, int | float):
            return float(latest)

    recent = reason_data.get("recentDatapoints")
    if isinstance(recent, list) and recent:
        return float(recent[-1])

    raise ValueError("CloudWatch alarm reasonData has no evaluated metric value")


def _threshold(reason_data: dict[str, Any], configuration: dict[str, Any]) -> float:
    threshold = reason_data.get("threshold", configuration.get("threshold"))
    if threshold is None:
        raise ValueError("CloudWatch alarm event has no threshold")
    return float(threshold)


def _condition(
    reason_data: dict[str, Any], configuration: dict[str, Any], metric_name: str
) -> Literal["above", "below"]:
    operator = str(
        reason_data.get("comparisonOperator", configuration.get("comparisonOperator", ""))
    ).lower()
    if "less" in operator or "lower" in operator:
        return "below"
    if "greater" in operator or "higher" in operator:
        return "above"
    if metric_name.lower() in {"freestoragespace", "free_storage_space"}:
        return "below"
    return "above"


def _resource(namespace: str, dimensions: dict[str, str]) -> tuple[str, str]:
    candidates: dict[str, tuple[str, ...]] = {
        "AWS/EC2": ("AutoScalingGroupName", "InstanceId"),
        "AWS/DynamoDB": ("TableName",),
        "AWS/RDS": ("DBInstanceIdentifier", "DBClusterIdentifier"),
    }
    resource_types = {
        "AWS/EC2": "EC2",
        "AWS/DynamoDB": "DYNAMODB",
        "AWS/RDS": "RDS",
    }
    for dimension in candidates[namespace]:
        value = dimensions.get(dimension)
        if value:
            return resource_types[namespace], value
    raise ValueError(f"CloudWatch {namespace} alarm has no supported resource dimension")


def _event_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        return uuid.uuid5(EVENT_NAMESPACE, f"eventbridge:{value}")


def cloudwatch_alarm_to_cloud_event(
    raw: dict[str, Any], *, service_key: str | None = None
) -> CloudEventEnvelope:
    """Convert one ALARM transition to the worker's strict internal contract."""
    aws_event = CloudWatchAlarmEvent.model_validate(raw)
    if aws_event.detail.state.value != "ALARM":
        raise ValueError("only CloudWatch ALARM state transitions create incidents")

    metric = _metric_configuration(aws_event.detail.configuration)
    namespace = str(metric["namespace"])
    metric_name = str(metric.get("name", ""))
    if not metric_name:
        raise ValueError("CloudWatch alarm metric name is missing")
    raw_dimensions = metric.get("dimensions", {})
    if not isinstance(raw_dimensions, dict):
        raise ValueError("CloudWatch alarm metric dimensions must be an object")
    dimensions = {str(key): str(value) for key, value in raw_dimensions.items()}
    resource_type, resource_id = _resource(namespace, dimensions)
    correlation_group = (
        f"service:{service_key.strip().lower()}"
        if service_key and service_key.strip()
        else f"resource:{resource_type.lower()}:{resource_id}"
    )
    reason_data = _reason_data(aws_event.detail.state)
    event_id = _event_uuid(aws_event.event_id)
    condition = _condition(reason_data, aws_event.detail.configuration, metric_name)
    payload = AwsResourceMetricPayload(
        resource_type=resource_type,
        resource_id=resource_id,
        metric_name=metric_name,
        value=_latest_value(reason_data),
        threshold=_threshold(reason_data, aws_event.detail.configuration),
        condition=condition,
        alarm_name=aws_event.detail.alarm_name,
        aws_account_id=aws_event.account,
        aws_region=aws_event.region,
        dimensions=dimensions,
        correlation_group=correlation_group,
        raw_event=raw,
    )
    incident_type = (
        "rds-storage-low"
        if resource_type == "RDS" and condition == "below"
        else "capacity-saturation"
    )
    return CloudEventEnvelope(
        event_id=event_id,
        event_type=EVENT_TYPE,
        source=f"aws:{aws_event.account}:{aws_event.region}:{resource_id}",
        occurred_at=aws_event.time,
        severity=Severity.HIGH,
        correlation_key=f"{resource_type.lower()}:{resource_id}:{incident_type}",
        payload=payload.model_dump(mode="json"),
        trace_id=uuid.uuid5(EVENT_NAMESPACE, f"trace:{event_id}"),
    )


def decode_event_message(
    body: str,
    service_key_resolver: Callable[[str], str | None] | None = None,
) -> CloudEventEnvelope:
    """Decode either an internal CloudEvent or a native EventBridge message."""
    raw = json.loads(body)
    if not isinstance(raw, dict):
        raise ValueError("SQS event body must be a JSON object")
    if raw.get("source") == "aws.cloudwatch" and raw.get("detail-type"):
        service_key = None
        resources = raw.get("resources")
        if service_key_resolver and isinstance(resources, list) and resources:
            service_key = service_key_resolver(str(resources[0]))
        return cloudwatch_alarm_to_cloud_event(raw, service_key=service_key)
    return CloudEventEnvelope.model_validate_json(body)
