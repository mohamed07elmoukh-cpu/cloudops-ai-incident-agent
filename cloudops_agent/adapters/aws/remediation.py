"""Least-privilege AWS capacity changes used by remediation runbooks."""

from __future__ import annotations

import os
from typing import Any, cast

import boto3
from botocore.config import Config


class AwsActionError(RuntimeError):
    """Raised when an AWS action is invalid or cannot be safely rolled back."""


class AwsRemediationAdapter:
    """Apply narrowly scoped EC2, DynamoDB, and RDS capacity changes."""

    def __init__(
        self,
        *,
        autoscaling_client: Any | None = None,
        dynamodb_client: Any | None = None,
        rds_client: Any | None = None,
    ) -> None:
        region_name = os.getenv("AWS_REGION", "us-east-1")
        endpoint_url = os.getenv("AWS_REMEDIATION_ENDPOINT_URL")
        external_config = Config(
            ignore_configured_endpoint_urls=True  # type: ignore[call-arg]
        )
        self.autoscaling = autoscaling_client or boto3.client(
            "autoscaling",
            region_name=region_name,
            endpoint_url=endpoint_url,
            config=external_config,
        )
        self.dynamodb = dynamodb_client or boto3.client(
            "dynamodb",
            region_name=region_name,
            endpoint_url=endpoint_url,
            config=external_config,
        )
        self.rds = rds_client or boto3.client(
            "rds",
            region_name=region_name,
            endpoint_url=endpoint_url,
            config=external_config,
        )

    def execute(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "scale_ec2_auto_scaling_group": self._scale_ec2,
            "scale_dynamodb_capacity": self._scale_dynamodb,
            "scale_rds_storage": self._scale_rds_storage,
            "scale_rds_compute": self._scale_rds_compute,
            "restore_ec2_auto_scaling_group": self._restore_ec2,
            "restore_dynamodb_capacity": self._restore_dynamodb,
            "restore_rds_storage_limit": self._restore_rds_storage_limit,
            "restore_rds_compute": self._restore_rds_compute,
        }
        handler = handlers.get(action)
        if handler is None:
            raise AwsActionError(f"unsupported AWS remediation action: {action}")
        return handler(arguments)

    def _scale_ec2(self, arguments: dict[str, Any]) -> dict[str, Any]:
        group_name = str(arguments["auto_scaling_group_name"])
        desired_capacity = int(arguments["desired_capacity"])
        response = self.autoscaling.describe_auto_scaling_groups(AutoScalingGroupNames=[group_name])
        groups = response.get("AutoScalingGroups", [])
        if not groups:
            raise AwsActionError(f"EC2 Auto Scaling group not found: {group_name}")
        group = groups[0]
        previous = int(group["DesiredCapacity"])
        maximum = int(group["MaxSize"])
        if desired_capacity <= previous:
            raise AwsActionError("EC2 desired capacity must increase")
        if desired_capacity > maximum:
            raise AwsActionError(
                f"EC2 desired capacity {desired_capacity} exceeds group maximum {maximum}"
            )
        self.autoscaling.set_desired_capacity(
            AutoScalingGroupName=group_name,
            DesiredCapacity=desired_capacity,
            HonorCooldown=True,
        )
        return {
            "service": "ec2",
            "resource_id": group_name,
            "previous_capacity": previous,
            "desired_capacity": desired_capacity,
            "reversible": True,
            "rollback": {
                "action": "restore_ec2_auto_scaling_group",
                "arguments": {
                    "auto_scaling_group_name": group_name,
                    "desired_capacity": previous,
                },
            },
        }

    def _restore_ec2(self, arguments: dict[str, Any]) -> dict[str, Any]:
        group_name = str(arguments["auto_scaling_group_name"])
        desired_capacity = int(arguments["desired_capacity"])
        self.autoscaling.set_desired_capacity(
            AutoScalingGroupName=group_name,
            DesiredCapacity=desired_capacity,
            HonorCooldown=False,
        )
        return {
            "service": "ec2",
            "resource_id": group_name,
            "restored_capacity": desired_capacity,
        }

    def _scale_dynamodb(self, arguments: dict[str, Any]) -> dict[str, Any]:
        table_name = str(arguments["table_name"])
        read_capacity = int(arguments["read_capacity_units"])
        write_capacity = int(arguments["write_capacity_units"])
        table = self.dynamodb.describe_table(TableName=table_name)["Table"]
        billing_mode = table.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED")
        if billing_mode == "PAY_PER_REQUEST":
            raise AwsActionError(
                f"DynamoDB table {table_name} uses on-demand capacity and has no RCU/WCU to set"
            )
        throughput = table["ProvisionedThroughput"]
        previous_read = int(throughput["ReadCapacityUnits"])
        previous_write = int(throughput["WriteCapacityUnits"])
        if read_capacity < previous_read or write_capacity < previous_write:
            raise AwsActionError("DynamoDB remediation cannot reduce provisioned capacity")
        if read_capacity == previous_read and write_capacity == previous_write:
            raise AwsActionError("DynamoDB capacity is already at the requested values")
        self.dynamodb.update_table(
            TableName=table_name,
            ProvisionedThroughput={
                "ReadCapacityUnits": read_capacity,
                "WriteCapacityUnits": write_capacity,
            },
        )
        return {
            "service": "dynamodb",
            "resource_id": table_name,
            "previous_read_capacity_units": previous_read,
            "previous_write_capacity_units": previous_write,
            "read_capacity_units": read_capacity,
            "write_capacity_units": write_capacity,
            "reversible": True,
            "rollback": {
                "action": "restore_dynamodb_capacity",
                "arguments": {
                    "table_name": table_name,
                    "read_capacity_units": previous_read,
                    "write_capacity_units": previous_write,
                },
            },
        }

    def _restore_dynamodb(self, arguments: dict[str, Any]) -> dict[str, Any]:
        table_name = str(arguments["table_name"])
        read_capacity = int(arguments["read_capacity_units"])
        write_capacity = int(arguments["write_capacity_units"])
        self.dynamodb.update_table(
            TableName=table_name,
            ProvisionedThroughput={
                "ReadCapacityUnits": read_capacity,
                "WriteCapacityUnits": write_capacity,
            },
        )
        return {
            "service": "dynamodb",
            "resource_id": table_name,
            "restored_read_capacity_units": read_capacity,
            "restored_write_capacity_units": write_capacity,
        }

    def _get_rds_instance(self, identifier: str) -> dict[str, Any]:
        response = self.rds.describe_db_instances(DBInstanceIdentifier=identifier)
        instances = response.get("DBInstances", [])
        if not instances:
            raise AwsActionError(f"RDS DB instance not found: {identifier}")
        return cast(dict[str, Any], instances[0])

    def _scale_rds_storage(self, arguments: dict[str, Any]) -> dict[str, Any]:
        identifier = str(arguments["db_instance_identifier"])
        allocated_storage = arguments.get("allocated_storage_gib")
        max_allocated_storage = arguments.get("max_allocated_storage_gib")
        instance = self._get_rds_instance(identifier)
        previous_allocated = int(instance["AllocatedStorage"])
        previous_max = instance.get("MaxAllocatedStorage")
        request: dict[str, Any] = {"DBInstanceIdentifier": identifier}
        irreversible = False
        if allocated_storage is not None:
            target_allocated = int(allocated_storage)
            if target_allocated <= previous_allocated:
                raise AwsActionError("RDS allocated storage must increase")
            request["AllocatedStorage"] = target_allocated
            irreversible = True
        if max_allocated_storage is not None:
            target_max = int(max_allocated_storage)
            minimum_max = int(request.get("AllocatedStorage", previous_allocated))
            if target_max <= minimum_max:
                raise AwsActionError("RDS maximum storage must exceed allocated storage")
            if previous_max is not None and target_max <= int(previous_max):
                raise AwsActionError("RDS maximum storage limit must increase")
            request["MaxAllocatedStorage"] = target_max
        if len(request) == 1:
            raise AwsActionError("RDS storage remediation requires a storage target")
        self.rds.modify_db_instance(**request)
        rollback = None
        if not irreversible and previous_max is not None:
            rollback = {
                "action": "restore_rds_storage_limit",
                "arguments": {
                    "db_instance_identifier": identifier,
                    "max_allocated_storage_gib": int(previous_max),
                },
            }
        reversible = rollback is not None
        return {
            "service": "rds",
            "resource_id": identifier,
            "previous_allocated_storage_gib": previous_allocated,
            "previous_max_allocated_storage_gib": previous_max,
            "allocated_storage_gib": request.get("AllocatedStorage", previous_allocated),
            "max_allocated_storage_gib": request.get("MaxAllocatedStorage", previous_max),
            "reversible": reversible,
            "rollback": rollback,
            "rollback_note": (
                "Allocated RDS storage cannot be reduced; manual recovery is required."
                if irreversible
                else None
            ),
        }

    def _restore_rds_storage_limit(self, arguments: dict[str, Any]) -> dict[str, Any]:
        identifier = str(arguments["db_instance_identifier"])
        maximum = int(arguments["max_allocated_storage_gib"])
        instance = self._get_rds_instance(identifier)
        if maximum <= int(instance["AllocatedStorage"]):
            raise AwsActionError("previous RDS storage limit is now below allocated storage")
        self.rds.modify_db_instance(
            DBInstanceIdentifier=identifier,
            MaxAllocatedStorage=maximum,
        )
        return {
            "service": "rds",
            "resource_id": identifier,
            "restored_max_allocated_storage_gib": maximum,
        }

    def _scale_rds_compute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        identifier = str(arguments["db_instance_identifier"])
        target_class = str(arguments["db_instance_class"])
        apply_immediately = bool(arguments.get("apply_immediately", False))
        instance = self._get_rds_instance(identifier)
        previous_class = str(instance["DBInstanceClass"])
        if target_class == previous_class:
            raise AwsActionError("RDS instance already uses the requested compute class")
        if _rds_class_capacity_rank(target_class) <= _rds_class_capacity_rank(previous_class):
            raise AwsActionError("RDS remediation must increase the DB instance class size")
        valid = self.rds.describe_valid_db_instance_modifications(DBInstanceIdentifier=identifier)
        valid_classes = {
            option["DBInstanceClass"]
            for option in valid.get("ValidDBInstanceModificationsMessage", {}).get(
                "ValidDBInstanceClass", []
            )
        }
        if valid_classes and target_class not in valid_classes:
            raise AwsActionError(f"RDS instance class is not a valid modification: {target_class}")
        self.rds.modify_db_instance(
            DBInstanceIdentifier=identifier,
            DBInstanceClass=target_class,
            ApplyImmediately=apply_immediately,
        )
        return {
            "service": "rds",
            "resource_id": identifier,
            "previous_db_instance_class": previous_class,
            "db_instance_class": target_class,
            "apply_immediately": apply_immediately,
            "reversible": True,
            "rollback": {
                "action": "restore_rds_compute",
                "arguments": {
                    "db_instance_identifier": identifier,
                    "db_instance_class": previous_class,
                    "apply_immediately": apply_immediately,
                },
            },
        }

    def _restore_rds_compute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        identifier = str(arguments["db_instance_identifier"])
        instance_class = str(arguments["db_instance_class"])
        apply_immediately = bool(arguments.get("apply_immediately", False))
        self.rds.modify_db_instance(
            DBInstanceIdentifier=identifier,
            DBInstanceClass=instance_class,
            ApplyImmediately=apply_immediately,
        )
        return {
            "service": "rds",
            "resource_id": identifier,
            "restored_db_instance_class": instance_class,
            "apply_immediately": apply_immediately,
        }


def _rds_class_capacity_rank(instance_class: str) -> int:
    """Return an ordering rank for conventional RDS instance size suffixes."""
    size = instance_class.rsplit(".", maxsplit=1)[-1]
    base_ranks = {"nano": 1, "micro": 2, "small": 3, "medium": 4, "large": 5}
    if size in base_ranks:
        return base_ranks[size]
    if size == "xlarge":
        return 6
    if size.endswith("xlarge") and size[:-6].isdigit():
        return 6 + int(size[:-6])
    raise AwsActionError(f"unsupported RDS instance class size: {instance_class}")
