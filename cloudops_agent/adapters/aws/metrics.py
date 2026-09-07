"""CloudWatch metric batches for the live infrastructure dashboard."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import boto3
from botocore.config import Config


class CloudWatchMetricsError(RuntimeError):
    """Raised when the dashboard metric snapshot cannot be produced safely."""


@dataclass(frozen=True)
class MetricSpec:
    query_id: str
    key: str
    label: str
    unit: str
    color: str
    namespace: str
    metric_name: str
    dimension_name: str
    statistic: str = "Average"
    scale: float = 1.0


RESOURCE_SPECS: dict[str, tuple[MetricSpec, ...]] = {
    "EC2": (
        MetricSpec(
            "ec2_cpu",
            "cpu",
            "CPU",
            "%",
            "#0b57d0",
            "AWS/EC2",
            "CPUUtilization",
            "AutoScalingGroupName",
        ),
        MetricSpec(
            "ec2_running",
            "in_service",
            "Instances actives",
            "instances",
            "#137333",
            "AWS/AutoScaling",
            "GroupInServiceInstances",
            "AutoScalingGroupName",
        ),
        MetricSpec(
            "ec2_desired",
            "desired",
            "Capacité désirée",
            "instances",
            "#9334e6",
            "AWS/AutoScaling",
            "GroupDesiredCapacity",
            "AutoScalingGroupName",
        ),
    ),
    "DYNAMODB": (
        MetricSpec(
            "ddb_read",
            "consumed_read",
            "RCU consommées",
            "RCU",
            "#0b57d0",
            "AWS/DynamoDB",
            "ConsumedReadCapacityUnits",
            "TableName",
            "Sum",
        ),
        MetricSpec(
            "ddb_read_limit",
            "provisioned_read",
            "RCU provisionnées",
            "RCU",
            "#137333",
            "AWS/DynamoDB",
            "ProvisionedReadCapacityUnits",
            "TableName",
        ),
        MetricSpec(
            "ddb_write",
            "consumed_write",
            "WCU consommées",
            "WCU",
            "#a142f4",
            "AWS/DynamoDB",
            "ConsumedWriteCapacityUnits",
            "TableName",
            "Sum",
        ),
        MetricSpec(
            "ddb_write_limit",
            "provisioned_write",
            "WCU provisionnées",
            "WCU",
            "#f9ab00",
            "AWS/DynamoDB",
            "ProvisionedWriteCapacityUnits",
            "TableName",
        ),
        MetricSpec(
            "ddb_throttle",
            "throttles",
            "Requêtes limitées",
            "requêtes",
            "#d93025",
            "AWS/DynamoDB",
            "ThrottledRequests",
            "TableName",
            "Sum",
        ),
    ),
    "RDS": (
        MetricSpec(
            "rds_cpu",
            "cpu",
            "CPU",
            "%",
            "#0b57d0",
            "AWS/RDS",
            "CPUUtilization",
            "DBInstanceIdentifier",
        ),
        MetricSpec(
            "rds_storage",
            "free_storage_gib",
            "Stockage libre",
            "GiB",
            "#137333",
            "AWS/RDS",
            "FreeStorageSpace",
            "DBInstanceIdentifier",
            scale=1 / (1024**3),
        ),
        MetricSpec(
            "rds_connections",
            "connections",
            "Connexions",
            "conn.",
            "#a142f4",
            "AWS/RDS",
            "DatabaseConnections",
            "DBInstanceIdentifier",
        ),
    ),
}


class CloudWatchMetricsReader:
    """Read configured EC2, DynamoDB, and RDS series in one CloudWatch batch."""

    def __init__(
        self,
        *,
        mode: Literal["aws", "demo"] | None = None,
        cloudwatch_client: Any | None = None,
        rds_client: Any | None = None,
        region_name: str | None = None,
    ) -> None:
        self.mode: Literal["aws", "demo"] = mode or (
            "aws" if os.getenv("CLOUDWATCH_METRICS_MODE", "demo").lower() == "aws" else "demo"
        )
        self.region = region_name or os.getenv("AWS_REGION", "us-east-1")
        self.resource_ids = {
            "EC2": os.getenv("CLOUDOPS_EC2_ASG_NAME", "api-production-asg"),
            "DYNAMODB": os.getenv("CLOUDOPS_DYNAMODB_TABLE_NAME", "orders"),
            "RDS": os.getenv("CLOUDOPS_RDS_INSTANCE_ID", "orders-db"),
        }
        self.cloudwatch = cloudwatch_client
        self.rds = rds_client
        if self.mode == "aws":
            endpoint_url = os.getenv("CLOUDWATCH_METRICS_ENDPOINT_URL")
            external_config = Config(
                ignore_configured_endpoint_urls=True  # type: ignore[call-arg]
            )
            self.cloudwatch = self.cloudwatch or boto3.client(
                "cloudwatch",
                region_name=self.region,
                endpoint_url=endpoint_url,
                config=external_config,
            )
            self.rds = self.rds or boto3.client(
                "rds",
                region_name=self.region,
                endpoint_url=os.getenv("CLOUDWATCH_RESOURCE_ENDPOINT_URL"),
                config=external_config,
            )

    def snapshot(self, window_minutes: int, *, now: datetime | None = None) -> dict[str, Any]:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        if self.mode == "demo":
            return self._demo_snapshot(window_minutes, current)
        return self._aws_snapshot(window_minutes, current)

    def _aws_snapshot(self, window_minutes: int, now: datetime) -> dict[str, Any]:
        if self.cloudwatch is None:
            raise CloudWatchMetricsError("CloudWatch client is not configured")
        period = 60 if window_minutes <= 180 else 300
        queries: list[dict[str, Any]] = []
        query_specs: dict[str, tuple[str, MetricSpec]] = {}
        for resource_type, specs in RESOURCE_SPECS.items():
            resource_id = self.resource_ids[resource_type]
            for spec in specs:
                queries.append(
                    {
                        "Id": spec.query_id,
                        "Label": spec.label,
                        "MetricStat": {
                            "Metric": {
                                "Namespace": spec.namespace,
                                "MetricName": spec.metric_name,
                                "Dimensions": [{"Name": spec.dimension_name, "Value": resource_id}],
                            },
                            "Period": period,
                            "Stat": spec.statistic,
                        },
                        "ReturnData": True,
                    }
                )
                query_specs[spec.query_id] = (resource_type, spec)
        try:
            response = self.cloudwatch.get_metric_data(
                MetricDataQueries=queries,
                StartTime=now - timedelta(minutes=window_minutes),
                EndTime=now,
                ScanBy="TimestampAscending",
                MaxDatapoints=5000,
            )
        except Exception as exc:
            raise CloudWatchMetricsError(f"CloudWatch GetMetricData failed: {exc}") from exc

        values: dict[str, dict[str, dict[str, float]]] = {
            resource_type: {} for resource_type in RESOURCE_SPECS
        }
        for result in response.get("MetricDataResults", []):
            match = query_specs.get(str(result.get("Id", "")))
            if match is None:
                continue
            resource_type, spec = match
            for timestamp, value in zip(
                result.get("Timestamps", []), result.get("Values", []), strict=False
            ):
                key = timestamp.astimezone(UTC).isoformat()
                values[resource_type].setdefault(key, {})[spec.key] = round(
                    float(value) * spec.scale, 2
                )
        resources = [
            self._resource_payload(
                resource_type,
                [
                    {"timestamp": timestamp, "values": point_values}
                    for timestamp, point_values in sorted(values[resource_type].items())
                ],
                metadata=self._metadata(resource_type),
            )
            for resource_type in RESOURCE_SPECS
        ]
        return self._snapshot_payload(window_minutes, now, period, resources)

    def _metadata(self, resource_type: str) -> dict[str, str]:
        if resource_type != "RDS" or self.rds is None:
            return {}
        try:
            instances = self.rds.describe_db_instances(
                DBInstanceIdentifier=self.resource_ids["RDS"]
            ).get("DBInstances", [])
        except Exception as exc:
            return {"instance_class": "indisponible", "metadata_error": str(exc)}
        if not instances:
            return {"instance_class": "introuvable"}
        return {"instance_class": str(instances[0].get("DBInstanceClass", "inconnue"))}

    def _demo_snapshot(self, window_minutes: int, now: datetime) -> dict[str, Any]:
        raw_period = window_minutes * 60 / 120
        period = max(10, int(math.ceil(raw_period / 10) * 10))
        end = now.replace(microsecond=0) - timedelta(seconds=now.second % period)
        count = int(window_minutes * 60 / period) + 1
        timestamps = [
            end - timedelta(seconds=period * (count - index - 1)) for index in range(count)
        ]
        remediation_index = max(2, int(count * 0.72))

        ec2_points: list[dict[str, Any]] = []
        dynamodb_points: list[dict[str, Any]] = []
        rds_points: list[dict[str, Any]] = []
        for index, timestamp in enumerate(timestamps):
            progress = index / max(1, count - 1)
            spike = math.exp(-(((progress - 0.64) / 0.13) ** 2))
            wave = math.sin(index * 0.55)
            remediated = index >= remediation_index
            ec2_points.append(
                self._point(
                    timestamp,
                    cpu=max(18, 43 + 46 * spike + wave * 3 - (13 if remediated else 0)),
                    in_service=4 if remediated else 2,
                    desired=4 if remediated else 2,
                )
            )
            dynamodb_points.append(
                self._point(
                    timestamp,
                    consumed_read=112 + 150 * spike + wave * 7 - (30 if remediated else 0),
                    provisioned_read=300 if remediated else 180,
                    consumed_write=56 + 88 * spike + wave * 4 - (18 if remediated else 0),
                    provisioned_write=170 if remediated else 100,
                    throttles=max(0, 22 * spike - (18 if remediated else 0)),
                )
            )
            rds_points.append(
                self._point(
                    timestamp,
                    cpu=max(22, 39 + 43 * spike + wave * 2 - (9 if remediated else 0)),
                    free_storage_gib=max(4, 18 - 11 * spike + (16 if remediated else 0)),
                    connections=max(20, 72 + 98 * spike + wave * 5 - (35 if remediated else 0)),
                )
            )

        resources = [
            self._resource_payload("EC2", ec2_points, demo_markers=self._demo_markers(timestamps)),
            self._resource_payload(
                "DYNAMODB", dynamodb_points, demo_markers=self._demo_markers(timestamps)
            ),
            self._resource_payload(
                "RDS",
                rds_points,
                metadata={"instance_class": "db.r6g.large"},
                demo_markers=self._demo_markers(timestamps),
            ),
        ]
        return self._snapshot_payload(window_minutes, now, period, resources)

    @staticmethod
    def _point(timestamp: datetime, **values: float) -> dict[str, Any]:
        return {
            "timestamp": timestamp.isoformat(),
            "values": {key: round(float(value), 2) for key, value in values.items()},
        }

    @staticmethod
    def _demo_markers(timestamps: list[datetime]) -> list[dict[str, Any]]:
        count = len(timestamps)
        positions = (
            (max(0, int(count * 0.57)), "detection", "Anomalie détectée"),
            (max(0, int(count * 0.72)), "remediation", "Capacité augmentée"),
            (max(0, int(count * 0.91)), "rollback", "Rollback contrôlé"),
        )
        return [
            {
                "timestamp": timestamps[min(index, count - 1)].isoformat(),
                "kind": kind,
                "label": label,
                "incident_id": None,
                "source": "demo",
            }
            for index, kind, label in positions
        ]

    def _resource_payload(
        self,
        resource_type: str,
        points: list[dict[str, Any]],
        *,
        metadata: dict[str, str] | None = None,
        demo_markers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        labels = {
            "EC2": ("Amazon EC2", "Auto Scaling Group"),
            "DYNAMODB": ("Amazon DynamoDB", "Table provisionnée"),
            "RDS": ("Amazon RDS", "Instance de base de données"),
        }
        latest = points[-1]["values"] if points else {}
        status = "healthy"
        if resource_type == "EC2" and float(latest.get("cpu", 0)) >= 80:
            status = "attention"
        elif resource_type == "DYNAMODB" and float(latest.get("throttles", 0)) > 0:
            status = "attention"
        elif resource_type == "RDS" and (
            float(latest.get("cpu", 0)) >= 80
            or 0 < float(latest.get("free_storage_gib", 100)) <= 10
        ):
            status = "attention"
        title, subtitle = labels[resource_type]
        return {
            "resource_type": resource_type,
            "resource_id": self.resource_ids[resource_type],
            "title": title,
            "subtitle": subtitle,
            "status": status,
            "metadata": metadata or {},
            "series": [
                {
                    "key": spec.key,
                    "label": spec.label,
                    "unit": spec.unit,
                    "color": spec.color,
                }
                for spec in RESOURCE_SPECS[resource_type]
            ],
            "points": points,
            "markers": demo_markers or [],
        }

    def _snapshot_payload(
        self,
        window_minutes: int,
        now: datetime,
        period_seconds: int,
        resources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "region": self.region,
            "generated_at": now.isoformat(),
            "window_minutes": window_minutes,
            "period_seconds": period_seconds,
            "refresh_seconds": 8,
            "resources": resources,
        }
