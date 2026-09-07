"""Server-side monthly cost estimation using the AWS Price List Query API."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config

HOURS_PER_MONTH = 730.0


class AwsPricingError(RuntimeError):
    """Raised when a safe server-side price cannot be determined."""


@dataclass(frozen=True)
class PricingEstimate:
    monthly_delta_usd: float
    currency: str
    source: str
    assumptions: list[str]
    line_items: list[dict[str, Any]]


class DemoPricingEstimator:
    """Deterministic local estimates that exercise cost policies without AWS calls."""

    def estimate(self, action: str, parameters: dict[str, Any]) -> PricingEstimate:
        handlers = {
            "scale_ec2_auto_scaling_group": self._ec2,
            "scale_dynamodb_capacity": self._dynamodb,
            "scale_rds_compute": self._rds_compute,
            "scale_rds_storage": self._rds_storage,
        }
        handler = handlers.get(action)
        if handler is None:
            raise AwsPricingError(f"local cost estimation does not support action: {action}")
        return handler(parameters)

    def _ec2(self, parameters: dict[str, Any]) -> PricingEstimate:
        target = int(parameters["desired_capacity"])
        current = 2
        monthly = max(0, target - current) * 0.096 * HOURS_PER_MONTH
        return self._estimate(
            monthly,
            [
                {
                    "resource": parameters["auto_scaling_group_name"],
                    "quantity_delta": max(0, target - current),
                    "unit": "instance",
                }
            ],
            [
                "Simulation locale",
                "Capacité EC2 initiale supposée: 2",
                "Tarif indicatif non contractuel",
            ],
        )

    def _dynamodb(self, parameters: dict[str, Any]) -> PricingEstimate:
        read_delta = max(0, int(parameters["read_capacity_units"]) - 100)
        write_delta = max(0, int(parameters["write_capacity_units"]) - 50)
        monthly = (read_delta * 0.00013 + write_delta * 0.00065) * HOURS_PER_MONTH
        return self._estimate(
            monthly,
            [
                {
                    "resource": parameters["table_name"],
                    "read_delta": read_delta,
                    "write_delta": write_delta,
                }
            ],
            [
                "Simulation locale",
                "Capacité supposée: 100 RCU / 50 WCU",
                "Tarifs indicatifs non contractuels",
            ],
        )

    def _rds_compute(self, parameters: dict[str, Any]) -> PricingEstimate:
        target_class = str(parameters["db_instance_class"])
        hourly_rates = {
            "db.t3.medium": 0.068,
            "db.m6g.large": 0.159,
            "db.r6g.large": 0.24,
            "db.r6g.xlarge": 0.48,
        }
        current_rate = hourly_rates["db.t3.medium"]
        target_rate = hourly_rates.get(target_class, 0.32)
        return self._estimate(
            max(0, target_rate - current_rate) * HOURS_PER_MONTH,
            [
                {
                    "resource": parameters["db_instance_identifier"],
                    "from": "db.t3.medium",
                    "to": target_class,
                }
            ],
            [
                "Simulation locale",
                "Classe RDS initiale supposée: db.t3.medium",
                "Tarif indicatif non contractuel",
            ],
        )

    def _rds_storage(self, parameters: dict[str, Any]) -> PricingEstimate:
        current = 100
        target = max(
            int(parameters.get("allocated_storage_gib") or current),
            int(parameters.get("max_allocated_storage_gib") or current),
        )
        delta = max(0, target - current)
        return self._estimate(
            delta * 0.115,
            [
                {
                    "resource": parameters["db_instance_identifier"],
                    "quantity_delta": delta,
                    "unit": "GB-month",
                }
            ],
            [
                "Simulation locale",
                "Stockage RDS initial supposé: 100 GiB",
                "Tarif indicatif non contractuel",
            ],
        )

    @staticmethod
    def _estimate(
        monthly_delta: float, line_items: list[dict[str, Any]], assumptions: list[str]
    ) -> PricingEstimate:
        return PricingEstimate(
            monthly_delta_usd=round(monthly_delta, 2),
            currency="USD",
            source="Simulation locale de coût",
            assumptions=assumptions,
            line_items=line_items,
        )


class AwsPricingEstimator:
    """Estimate incremental on-demand cost before an AWS capacity change."""

    def __init__(
        self,
        *,
        pricing_client: Any | None = None,
        autoscaling_client: Any | None = None,
        ec2_client: Any | None = None,
        dynamodb_client: Any | None = None,
        rds_client: Any | None = None,
        region_name: str | None = None,
    ) -> None:
        self.region: str = region_name or os.getenv("AWS_REGION") or "us-east-1"
        external_config = Config(
            ignore_configured_endpoint_urls=True  # type: ignore[call-arg]
        )
        self.resource_endpoint_url = os.getenv("AWS_PRICING_RESOURCE_ENDPOINT_URL")
        self.pricing = pricing_client or boto3.client(
            "pricing",
            region_name=os.getenv("AWS_PRICING_REGION", "us-east-1"),
            endpoint_url=os.getenv("AWS_PRICING_ENDPOINT_URL"),
            config=external_config,
        )
        self.autoscaling = autoscaling_client or boto3.client(
            "autoscaling",
            region_name=self.region,
            endpoint_url=self.resource_endpoint_url,
            config=external_config,
        )
        self.ec2 = ec2_client
        self.dynamodb = dynamodb_client or boto3.client(
            "dynamodb",
            region_name=self.region,
            endpoint_url=self.resource_endpoint_url,
            config=external_config,
        )
        self.rds = rds_client or boto3.client(
            "rds",
            region_name=self.region,
            endpoint_url=self.resource_endpoint_url,
            config=external_config,
        )

    def estimate(self, action: str, parameters: dict[str, Any]) -> PricingEstimate:
        handlers = {
            "scale_ec2_auto_scaling_group": self._ec2,
            "scale_dynamodb_capacity": self._dynamodb,
            "scale_rds_compute": self._rds_compute,
            "scale_rds_storage": self._rds_storage,
        }
        handler = handlers.get(action)
        if handler is None:
            raise AwsPricingError(f"AWS Pricing does not support action: {action}")
        try:
            return handler(parameters)
        except AwsPricingError:
            raise
        except Exception as exc:
            raise AwsPricingError(f"AWS cost estimation failed for {action}: {exc}") from exc

    def _ec2(self, parameters: dict[str, Any]) -> PricingEstimate:
        name = str(parameters["auto_scaling_group_name"])
        groups = self.autoscaling.describe_auto_scaling_groups(AutoScalingGroupNames=[name]).get(
            "AutoScalingGroups", []
        )
        if not groups:
            raise AwsPricingError(f"Auto Scaling group not found: {name}")
        group = groups[0]
        current = int(group["DesiredCapacity"])
        target = int(parameters["desired_capacity"])
        if target <= current:
            raise AwsPricingError("EC2 target capacity must be greater than current capacity")
        instance_type = self._asg_instance_type(group)
        hourly = self._rate(
            "AmazonEC2",
            {
                "productFamily": "Compute Instance",
                "regionCode": self.region,
                "instanceType": instance_type,
                "operatingSystem": "Linux",
                "tenancy": "Shared",
                "preInstalledSw": "NA",
                "capacitystatus": "Used",
            },
            {"Hrs", "Hours"},
        )
        delta = target - current
        monthly = delta * hourly * HOURS_PER_MONTH
        return self._estimate(
            monthly,
            [{"resource": name, "quantity_delta": delta, "unit": "instance", "hourly_usd": hourly}],
            ["Linux shared-tenancy On-Demand price", "730 hours per month"],
        )

    def _asg_instance_type(self, group: dict[str, Any]) -> str:
        running_types = {
            str(instance["InstanceType"])
            for instance in group.get("Instances", [])
            if instance.get("InstanceType")
        }
        if len(running_types) == 1:
            return running_types.pop()
        if len(running_types) > 1:
            raise AwsPricingError("mixed-instance Auto Scaling pricing is ambiguous")

        mixed = group.get("MixedInstancesPolicy", {}).get("LaunchTemplate", {})
        override_types = {
            str(item["InstanceType"])
            for item in mixed.get("Overrides", [])
            if item.get("InstanceType")
        }
        if len(override_types) == 1:
            return override_types.pop()
        if len(override_types) > 1:
            raise AwsPricingError("mixed-instance Auto Scaling pricing is ambiguous")

        specification = group.get("LaunchTemplate") or mixed.get("LaunchTemplateSpecification")
        if not specification:
            raise AwsPricingError("Auto Scaling group has no priceable instance type")
        if self.ec2 is None:
            self.ec2 = boto3.client(
                "ec2",
                region_name=self.region,
                endpoint_url=self.resource_endpoint_url,
                config=Config(
                    ignore_configured_endpoint_urls=True  # type: ignore[call-arg]
                ),
            )
        request: dict[str, Any] = {"Versions": [str(specification.get("Version", "$Default"))]}
        if specification.get("LaunchTemplateId"):
            request["LaunchTemplateId"] = specification["LaunchTemplateId"]
        elif specification.get("LaunchTemplateName"):
            request["LaunchTemplateName"] = specification["LaunchTemplateName"]
        else:
            raise AwsPricingError("Auto Scaling launch template identity is missing")
        versions = self.ec2.describe_launch_template_versions(**request).get(
            "LaunchTemplateVersions", []
        )
        instance_type = (
            versions[0].get("LaunchTemplateData", {}).get("InstanceType") if versions else None
        )
        if not instance_type:
            raise AwsPricingError("launch template has no fixed instance type")
        return str(instance_type)

    def _dynamodb(self, parameters: dict[str, Any]) -> PricingEstimate:
        name = str(parameters["table_name"])
        table = self.dynamodb.describe_table(TableName=name)["Table"]
        mode = table.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED")
        if mode == "PAY_PER_REQUEST":
            raise AwsPricingError("DynamoDB on-demand tables do not have provisioned RCU/WCU")
        throughput = table["ProvisionedThroughput"]
        read_delta = max(
            0, int(parameters["read_capacity_units"]) - int(throughput["ReadCapacityUnits"])
        )
        write_delta = max(
            0, int(parameters["write_capacity_units"]) - int(throughput["WriteCapacityUnits"])
        )
        read_rate = self._rate(
            "AmazonDynamoDB",
            {"regionCode": self.region, "group": "DDB-ReadUnits"},
            {"Hrs", "ReadCapacityUnit-Hrs", "RCU-Hrs"},
        )
        write_rate = self._rate(
            "AmazonDynamoDB",
            {"regionCode": self.region, "group": "DDB-WriteUnits"},
            {"Hrs", "WriteCapacityUnit-Hrs", "WCU-Hrs"},
        )
        monthly = (read_delta * read_rate + write_delta * write_rate) * HOURS_PER_MONTH
        return self._estimate(
            monthly,
            [
                {
                    "resource": name,
                    "quantity_delta": read_delta,
                    "unit": "RCU",
                    "hourly_usd": read_rate,
                },
                {
                    "resource": name,
                    "quantity_delta": write_delta,
                    "unit": "WCU",
                    "hourly_usd": write_rate,
                },
            ],
            ["Provisioned capacity", "No reserved-capacity discount", "730 hours per month"],
        )

    def _rds_compute(self, parameters: dict[str, Any]) -> PricingEstimate:
        instance = self._rds_instance(str(parameters["db_instance_identifier"]))
        engine = _rds_engine(str(instance["Engine"]))
        base_filters: dict[str, str] = {
            "productFamily": "Database Instance",
            "regionCode": self.region,
            "databaseEngine": engine,
            "deploymentOption": "Multi-AZ" if instance.get("MultiAZ") else "Single-AZ",
        }
        current_class = str(instance["DBInstanceClass"])
        target_class = str(parameters["db_instance_class"])
        current_rate = self._rate(
            "AmazonRDS", {**base_filters, "instanceType": current_class}, {"Hrs", "Hours"}
        )
        target_rate = self._rate(
            "AmazonRDS", {**base_filters, "instanceType": target_class}, {"Hrs", "Hours"}
        )
        monthly = max(0.0, target_rate - current_rate) * HOURS_PER_MONTH
        return self._estimate(
            monthly,
            [
                {
                    "resource": instance["DBInstanceIdentifier"],
                    "from": current_class,
                    "to": target_class,
                    "hourly_delta_usd": max(0.0, target_rate - current_rate),
                }
            ],
            [
                "RDS On-Demand instance price",
                "Existing engine and deployment option",
                "730 hours per month",
            ],
        )

    def _rds_storage(self, parameters: dict[str, Any]) -> PricingEstimate:
        instance = self._rds_instance(str(parameters["db_instance_identifier"]))
        current = int(instance["AllocatedStorage"])
        allocated_target = parameters.get("allocated_storage_gib")
        maximum_target = parameters.get("max_allocated_storage_gib")
        target = max(
            int(allocated_target) if allocated_target is not None else current,
            int(maximum_target) if maximum_target is not None else current,
        )
        delta = max(0, target - current)
        filters: dict[str, str] = {
            "productFamily": "Database Storage",
            "regionCode": self.region,
            "databaseEngine": _rds_engine(str(instance["Engine"])),
        }
        volume_type = _rds_volume_type(str(instance.get("StorageType", "")))
        if volume_type:
            filters["volumeType"] = volume_type
        monthly_rate = self._rate("AmazonRDS", filters, {"GB-Mo", "GB-month"})
        return self._estimate(
            delta * monthly_rate,
            [
                {
                    "resource": instance["DBInstanceIdentifier"],
                    "quantity_delta": delta,
                    "unit": "GB-month",
                    "unit_price_usd": monthly_rate,
                }
            ],
            [
                "Maximum storage exposure including the autoscaling ceiling",
                "RDS storage list price",
                "Backup, IOPS, and data transfer excluded",
            ],
        )

    def _rds_instance(self, identifier: str) -> dict[str, Any]:
        instances = self.rds.describe_db_instances(DBInstanceIdentifier=identifier).get(
            "DBInstances", []
        )
        if not instances:
            raise AwsPricingError(f"RDS instance not found: {identifier}")
        return dict(instances[0])

    def _rate(self, service_code: str, attributes: dict[str, str], units: set[str]) -> float:
        response = self.pricing.get_products(
            ServiceCode=service_code,
            FormatVersion="aws_v1",
            MaxResults=100,
            Filters=[
                {"Type": "TERM_MATCH", "Field": field, "Value": value}
                for field, value in attributes.items()
            ],
        )
        rates: list[float] = []
        for raw_product in response.get("PriceList", []):
            product = json.loads(raw_product) if isinstance(raw_product, str) else raw_product
            for term in product.get("terms", {}).get("OnDemand", {}).values():
                for dimension in term.get("priceDimensions", {}).values():
                    if dimension.get("unit") in units:
                        rates.append(float(dimension.get("pricePerUnit", {}).get("USD", 0)))
        positive = sorted({rate for rate in rates if rate > 0})
        if not positive:
            raise AwsPricingError(
                f"no unambiguous USD price for {service_code} with filters {attributes}"
            )
        if len(positive) > 1:
            raise AwsPricingError(
                f"multiple USD prices for {service_code} with filters {attributes}"
            )
        return positive[0]

    @staticmethod
    def _estimate(
        monthly_delta: float, line_items: list[dict[str, Any]], assumptions: list[str]
    ) -> PricingEstimate:
        return PricingEstimate(
            monthly_delta_usd=round(monthly_delta, 2),
            currency="USD",
            source="AWS Price List Query API",
            assumptions=assumptions,
            line_items=line_items,
        )


def _rds_engine(engine: str) -> str:
    values = {
        "postgres": "PostgreSQL",
        "mysql": "MySQL",
        "mariadb": "MariaDB",
        "oracle-ee": "Oracle",
        "oracle-se2": "Oracle",
        "sqlserver-ee": "SQL Server",
        "sqlserver-se": "SQL Server",
        "sqlserver-ex": "SQL Server",
        "sqlserver-web": "SQL Server",
        "aurora-postgresql": "Aurora PostgreSQL",
        "aurora-mysql": "Aurora MySQL",
    }
    return values.get(engine, engine)


def _rds_volume_type(storage_type: str) -> str | None:
    return {
        "gp2": "General Purpose",
        "gp3": "General Purpose",
        "io1": "Provisioned IOPS",
        "io2": "Provisioned IOPS",
        "standard": "Magnetic",
    }.get(storage_type)
