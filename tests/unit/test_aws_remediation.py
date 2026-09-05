from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from cloudops_agent.adapters.aws import AwsActionError, AwsRemediationAdapter
from cloudops_agent.models import Incident, IncidentStatus, Severity
from cloudops_agent.remediation.executor import AwsRemediationExecutor
from cloudops_agent.remediation.runbooks import RunbookLoader


def adapter_with_clients() -> tuple[AwsRemediationAdapter, Mock, Mock, Mock]:
    autoscaling = Mock()
    dynamodb = Mock()
    rds = Mock()
    adapter = AwsRemediationAdapter(
        autoscaling_client=autoscaling,
        dynamodb_client=dynamodb,
        rds_client=rds,
    )
    return adapter, autoscaling, dynamodb, rds


def test_ec2_capacity_is_increased_and_can_be_rolled_back() -> None:
    adapter, autoscaling, _, _ = adapter_with_clients()
    autoscaling.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [{"DesiredCapacity": 2, "MaxSize": 6}]
    }

    result = adapter.execute(
        "scale_ec2_auto_scaling_group",
        {"auto_scaling_group_name": "api-asg", "desired_capacity": 4},
    )
    adapter.execute(result["rollback"]["action"], result["rollback"]["arguments"])

    assert result["previous_capacity"] == 2
    autoscaling.set_desired_capacity.assert_any_call(
        AutoScalingGroupName="api-asg", DesiredCapacity=4, HonorCooldown=True
    )
    autoscaling.set_desired_capacity.assert_any_call(
        AutoScalingGroupName="api-asg", DesiredCapacity=2, HonorCooldown=False
    )


def test_dynamodb_provisioned_capacity_is_increased() -> None:
    adapter, _, dynamodb, _ = adapter_with_clients()
    dynamodb.describe_table.return_value = {
        "Table": {
            "BillingModeSummary": {"BillingMode": "PROVISIONED"},
            "ProvisionedThroughput": {
                "ReadCapacityUnits": 10,
                "WriteCapacityUnits": 5,
            },
        }
    }

    result = adapter.execute(
        "scale_dynamodb_capacity",
        {"table_name": "orders", "read_capacity_units": 20, "write_capacity_units": 10},
    )

    assert result["previous_read_capacity_units"] == 10
    dynamodb.update_table.assert_called_once_with(
        TableName="orders",
        ProvisionedThroughput={"ReadCapacityUnits": 20, "WriteCapacityUnits": 10},
    )


def test_dynamodb_on_demand_table_is_rejected() -> None:
    adapter, _, dynamodb, _ = adapter_with_clients()
    dynamodb.describe_table.return_value = {
        "Table": {"BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"}}
    }

    with pytest.raises(AwsActionError, match="on-demand"):
        adapter.execute(
            "scale_dynamodb_capacity",
            {"table_name": "orders", "read_capacity_units": 20, "write_capacity_units": 10},
        )


def test_rds_storage_limit_is_reversible_but_allocated_storage_is_not() -> None:
    adapter, _, _, rds = adapter_with_clients()
    rds.describe_db_instances.return_value = {
        "DBInstances": [{"AllocatedStorage": 100, "MaxAllocatedStorage": 200}]
    }

    limit_result = adapter.execute(
        "scale_rds_storage",
        {"db_instance_identifier": "orders-db", "max_allocated_storage_gib": 300},
    )
    allocated_result = adapter.execute(
        "scale_rds_storage",
        {"db_instance_identifier": "orders-db", "allocated_storage_gib": 150},
    )

    assert limit_result["reversible"] is True
    assert allocated_result["reversible"] is False
    assert "cannot be reduced" in allocated_result["rollback_note"]


def test_rds_compute_change_records_previous_class() -> None:
    adapter, _, _, rds = adapter_with_clients()
    rds.describe_db_instances.return_value = {
        "DBInstances": [{"DBInstanceClass": "db.t3.medium"}]
    }
    rds.describe_valid_db_instance_modifications.return_value = {
        "ValidDBInstanceModificationsMessage": {
            "ValidDBInstanceClass": [{"DBInstanceClass": "db.t3.large"}]
        }
    }

    result = adapter.execute(
        "scale_rds_compute",
        {
            "db_instance_identifier": "orders-db",
            "db_instance_class": "db.t3.large",
            "apply_immediately": False,
        },
    )

    assert result["previous_db_instance_class"] == "db.t3.medium"
    rds.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="orders-db",
        DBInstanceClass="db.t3.large",
        ApplyImmediately=False,
    )


def test_real_executor_audits_aws_change_and_rollback(session: Session) -> None:
    adapter, autoscaling, _, _ = adapter_with_clients()
    autoscaling.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [{"DesiredCapacity": 2, "MaxSize": 6}]
    }
    incident = Incident(
        source="api-asg",
        incident_type="EC2_CAPACITY_SATURATION",
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        title="EC2 saturation",
        description="CPU threshold breached",
        correlation_key="ec2:api-asg:capacity",
    )
    session.add(incident)
    session.commit()
    executor = AwsRemediationExecutor(session, adapter)

    execution = executor.execute(
        incident,
        RunbookLoader().load("scale_ec2_auto_scaling_group"),
        {"auto_scaling_group_name": "api-asg", "desired_capacity": 4},
        estimated_monthly_cost_delta_usd=50,
    )
    executor.rollback(
        incident,
        execution,
        RunbookLoader().load("scale_ec2_auto_scaling_group"),
    )

    assert execution.output["simulated"] is False
    assert execution.output["result"]["previous_capacity"] == 2
    assert execution.status == "ROLLED_BACK"
    assert incident.status == IncidentStatus.ESCALATED
