from __future__ import annotations

import json
from typing import Any
from unittest.mock import Mock

import pytest

from cloudops_agent.adapters.aws.correlation import CloudWatchAlarmTagResolver
from cloudops_agent.adapters.aws.pricing import (
    AwsPricingError,
    AwsPricingEstimator,
    DemoPricingEstimator,
)


def price(rate: float, unit: str) -> dict[str, Any]:
    document = {
        "terms": {
            "OnDemand": {
                "sku.term": {
                    "priceDimensions": {
                        "sku.term.dimension": {
                            "unit": unit,
                            "pricePerUnit": {"USD": str(rate)},
                        }
                    }
                }
            }
        }
    }
    return {"PriceList": [json.dumps(document)]}


def test_rejects_ambiguous_price_results() -> None:
    first = price(0.10, "Hrs")["PriceList"]
    second = price(0.20, "Hrs")["PriceList"]
    pricing = Mock()
    pricing.get_products.return_value = {"PriceList": [*first, *second]}
    autoscaling = Mock()
    autoscaling.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [{"DesiredCapacity": 1, "Instances": [{"InstanceType": "m5.large"}]}]
    }
    estimator = AwsPricingEstimator(
        pricing_client=pricing,
        autoscaling_client=autoscaling,
        dynamodb_client=Mock(),
        rds_client=Mock(),
        region_name="eu-west-1",
    )

    with pytest.raises(AwsPricingError, match="multiple USD prices"):
        estimator.estimate(
            "scale_ec2_auto_scaling_group",
            {"auto_scaling_group_name": "api-asg", "desired_capacity": 2},
        )


def test_resolves_application_key_from_cloudwatch_alarm_tag() -> None:
    cloudwatch = Mock()
    cloudwatch.list_tags_for_resource.return_value = {
        "Tags": [
            {"Key": "environment", "Value": "production"},
            {"Key": "cloudops:service", "Value": "checkout"},
        ]
    }
    resolver = CloudWatchAlarmTagResolver("cloudops:service", cloudwatch)

    assert resolver.resolve("arn:aws:cloudwatch:eu-west-1:123:alarm:cloudops-checkout") == (
        "checkout"
    )


def test_estimates_ec2_increment_from_current_asg_capacity() -> None:
    pricing = Mock()
    pricing.get_products.return_value = price(0.10, "Hrs")
    autoscaling = Mock()
    autoscaling.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [
            {
                "DesiredCapacity": 2,
                "Instances": [{"InstanceType": "m5.large"}],
            }
        ]
    }
    estimator = AwsPricingEstimator(
        pricing_client=pricing,
        autoscaling_client=autoscaling,
        dynamodb_client=Mock(),
        rds_client=Mock(),
        region_name="eu-west-1",
    )

    estimate = estimator.estimate(
        "scale_ec2_auto_scaling_group",
        {"auto_scaling_group_name": "checkout-asg", "desired_capacity": 4},
    )

    assert estimate.monthly_delta_usd == 146.0
    assert estimate.source == "AWS Price List Query API"


def test_prices_empty_asg_from_launch_template() -> None:
    pricing = Mock()
    pricing.get_products.return_value = price(0.20, "Hrs")
    autoscaling = Mock()
    autoscaling.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [
            {
                "DesiredCapacity": 0,
                "Instances": [],
                "LaunchTemplate": {
                    "LaunchTemplateId": "lt-123",
                    "Version": "$Default",
                },
            }
        ]
    }
    ec2 = Mock()
    ec2.describe_launch_template_versions.return_value = {
        "LaunchTemplateVersions": [{"LaunchTemplateData": {"InstanceType": "m6i.large"}}]
    }
    estimator = AwsPricingEstimator(
        pricing_client=pricing,
        autoscaling_client=autoscaling,
        ec2_client=ec2,
        dynamodb_client=Mock(),
        rds_client=Mock(),
        region_name="eu-west-1",
    )

    estimate = estimator.estimate(
        "scale_ec2_auto_scaling_group",
        {"auto_scaling_group_name": "empty-asg", "desired_capacity": 1},
    )

    assert estimate.monthly_delta_usd == 146.0
    ec2.describe_launch_template_versions.assert_called_once_with(
        LaunchTemplateId="lt-123", Versions=["$Default"]
    )


def test_estimates_dynamodb_provisioned_capacity_delta() -> None:
    pricing = Mock()
    pricing.get_products.side_effect = [price(0.00013, "Hrs"), price(0.00065, "Hrs")]
    dynamodb = Mock()
    dynamodb.describe_table.return_value = {
        "Table": {
            "ProvisionedThroughput": {
                "ReadCapacityUnits": 10,
                "WriteCapacityUnits": 5,
            }
        }
    }
    estimator = AwsPricingEstimator(
        pricing_client=pricing,
        autoscaling_client=Mock(),
        dynamodb_client=dynamodb,
        rds_client=Mock(),
        region_name="eu-west-1",
    )

    estimate = estimator.estimate(
        "scale_dynamodb_capacity",
        {"table_name": "orders", "read_capacity_units": 20, "write_capacity_units": 8},
    )

    assert estimate.monthly_delta_usd == 2.37


def test_estimates_rds_compute_and_storage_deltas() -> None:
    pricing = Mock()
    pricing.get_products.side_effect = [
        price(0.034, "Hrs"),
        price(0.068, "Hrs"),
        price(0.115, "GB-Mo"),
    ]
    rds = Mock()
    rds.describe_db_instances.return_value = {
        "DBInstances": [
            {
                "DBInstanceIdentifier": "orders-db",
                "DBInstanceClass": "db.t3.small",
                "Engine": "postgres",
                "MultiAZ": False,
                "AllocatedStorage": 100,
                "StorageType": "gp2",
            }
        ]
    }
    estimator = AwsPricingEstimator(
        pricing_client=pricing,
        autoscaling_client=Mock(),
        dynamodb_client=Mock(),
        rds_client=rds,
        region_name="eu-west-1",
    )

    compute = estimator.estimate(
        "scale_rds_compute",
        {"db_instance_identifier": "orders-db", "db_instance_class": "db.t3.medium"},
    )
    storage = estimator.estimate(
        "scale_rds_storage",
        {"db_instance_identifier": "orders-db", "allocated_storage_gib": 150},
    )

    assert compute.monthly_delta_usd == 24.82
    assert storage.monthly_delta_usd == 5.75


def test_rds_autoscaling_limit_uses_maximum_cost_exposure() -> None:
    pricing = Mock()
    pricing.get_products.return_value = price(0.10, "GB-Mo")
    rds = Mock()
    rds.describe_db_instances.return_value = {
        "DBInstances": [
            {
                "DBInstanceIdentifier": "orders-db",
                "DBInstanceClass": "db.t3.small",
                "Engine": "postgres",
                "AllocatedStorage": 100,
                "StorageType": "gp2",
            }
        ]
    }
    estimator = AwsPricingEstimator(
        pricing_client=pricing,
        autoscaling_client=Mock(),
        dynamodb_client=Mock(),
        rds_client=rds,
        region_name="eu-west-1",
    )

    estimate = estimator.estimate(
        "scale_rds_storage",
        {
            "db_instance_identifier": "orders-db",
            "allocated_storage_gib": None,
            "max_allocated_storage_gib": 500,
        },
    )

    assert estimate.monthly_delta_usd == 40.0
    assert "Maximum storage exposure" in estimate.assumptions[0]


def test_demo_estimates_rds_storage_without_an_aws_call() -> None:
    estimate = DemoPricingEstimator().estimate(
        "scale_rds_storage",
        {
            "db_instance_identifier": "orders-db",
            "allocated_storage_gib": None,
            "max_allocated_storage_gib": 500,
        },
    )

    assert estimate.monthly_delta_usd == 46.0
    assert estimate.source == "Simulation locale de coût"
    assert estimate.line_items[0]["quantity_delta"] == 400


def test_real_pricing_clients_ignore_the_global_localstack_endpoint(monkeypatch: Any) -> None:
    clients: list[tuple[str, dict[str, Any]]] = []

    def fake_client(service_name: str, **kwargs: Any) -> Mock:
        clients.append((service_name, kwargs))
        return Mock()

    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://localstack:4566")
    monkeypatch.delenv("AWS_PRICING_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("AWS_PRICING_RESOURCE_ENDPOINT_URL", raising=False)
    monkeypatch.setattr("cloudops_agent.adapters.aws.pricing.boto3.client", fake_client)

    AwsPricingEstimator(region_name="eu-west-1")

    assert [name for name, _ in clients] == ["pricing", "autoscaling", "dynamodb", "rds"]
    for _, kwargs in clients:
        assert kwargs["endpoint_url"] is None
        assert kwargs["config"].ignore_configured_endpoint_urls is True
