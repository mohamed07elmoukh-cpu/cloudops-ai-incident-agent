from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cloudops_agent.adapters.aws.metrics import CloudWatchMetricsReader


class FakeCloudWatch:
    def __init__(self, timestamp: datetime) -> None:
        self.timestamp = timestamp
        self.request: dict[str, Any] = {}

    def get_metric_data(self, **request: Any) -> dict[str, Any]:
        self.request = request
        return {
            "MetricDataResults": [
                {"Id": "ec2_cpu", "Timestamps": [self.timestamp], "Values": [82.5]},
                {"Id": "ec2_running", "Timestamps": [self.timestamp], "Values": [3]},
                {"Id": "ec2_desired", "Timestamps": [self.timestamp], "Values": [4]},
                {"Id": "ddb_throttle", "Timestamps": [self.timestamp], "Values": [7]},
                {"Id": "rds_cpu", "Timestamps": [self.timestamp], "Values": [44]},
                {
                    "Id": "rds_storage",
                    "Timestamps": [self.timestamp],
                    "Values": [20 * 1024**3],
                },
                {"Id": "rds_connections", "Timestamps": [self.timestamp], "Values": [91]},
            ]
        }


class FakeRds:
    def describe_db_instances(self, **_: Any) -> dict[str, Any]:
        return {"DBInstances": [{"DBInstanceClass": "db.r6g.large"}]}


def test_reads_all_cloudwatch_series_in_one_batch(monkeypatch: Any) -> None:
    monkeypatch.setenv("CLOUDOPS_EC2_ASG_NAME", "checkout-asg")
    monkeypatch.setenv("CLOUDOPS_DYNAMODB_TABLE_NAME", "orders")
    monkeypatch.setenv("CLOUDOPS_RDS_INSTANCE_ID", "orders-db")
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    cloudwatch = FakeCloudWatch(now)
    reader = CloudWatchMetricsReader(
        mode="aws",
        cloudwatch_client=cloudwatch,
        rds_client=FakeRds(),
        region_name="eu-west-1",
    )

    snapshot = reader.snapshot(60, now=now)

    assert snapshot["mode"] == "aws"
    assert len(cloudwatch.request["MetricDataQueries"]) == 11
    assert cloudwatch.request["ScanBy"] == "TimestampAscending"
    ec2, dynamodb, rds = snapshot["resources"]
    assert ec2["status"] == "attention"
    assert ec2["points"][0]["values"]["desired"] == 4
    assert dynamodb["points"][0]["values"]["throttles"] == 7
    assert rds["points"][0]["values"]["free_storage_gib"] == 20
    assert rds["metadata"]["instance_class"] == "db.r6g.large"


def test_demo_snapshot_contains_three_resources_and_lifecycle_markers() -> None:
    snapshot = CloudWatchMetricsReader(mode="demo").snapshot(
        15, now=datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    )

    assert snapshot["period_seconds"] == 10
    assert [resource["resource_type"] for resource in snapshot["resources"]] == [
        "EC2",
        "DYNAMODB",
        "RDS",
    ]
    assert all(len(resource["points"]) == 91 for resource in snapshot["resources"])
    assert {marker["kind"] for marker in snapshot["resources"][0]["markers"]} == {
        "detection",
        "remediation",
        "rollback",
    }
