# AWS capacity remediation

## Safety mode

AWS runbooks use the simulated executor by default. This exercises validation,
approval, cost, cooldown, audit, verification, and rollback behavior without
changing AWS resources.

Set `REMEDIATION_MODE=aws` only in a protected deployment whose API callers are
authenticated. The process must use an IAM role or AWS credentials for the
target account. `AWS_REMEDIATION_ENDPOINT_URL` is optional and intended for a
dedicated compatible test endpoint; the SQS-specific `AWS_ENDPOINT_URL` is not
reused by the remediation adapter.

The global monthly cost-increase ceiling defaults to USD 500 and can be lowered:

```shell
REMEDIATION_MODE=aws
REMEDIATION_MAX_MONTHLY_COST_DELTA_USD=250
```

The effective ceiling is the smaller of this value and the limit declared by
the selected runbook. The current API expects a trusted controller or operator
to supply `estimated_monthly_cost_delta_usd`; a production deployment should
replace that input with a server-side AWS Pricing/FinOps estimate.

## Least-privilege permissions

The executor needs only the actions used by enabled runbooks:

```text
autoscaling:DescribeAutoScalingGroups
autoscaling:SetDesiredCapacity
dynamodb:DescribeTable
dynamodb:UpdateTable
rds:DescribeDBInstances
rds:DescribeValidDBInstanceModifications
rds:ModifyDBInstance
```

Mutation permissions should be restricted to approved Auto Scaling Groups,
DynamoDB tables, and RDS instances. The API itself must be authenticated before
real mode is enabled.

## Example: EC2 Auto Scaling

Create an incident from a capacity signal:

```shell
curl -X POST http://localhost:8000/api/detection/resources/evaluate \
  -H "Content-Type: application/json" \
  -d '{"resource_type":"EC2","resource_id":"api-asg","metric_name":"CPUUtilization","value":92,"threshold":80,"condition":"above","timestamp":"2026-09-05T12:00:00Z"}'
```

Use its incident ID to request the capacity increase:

```shell
curl -X POST http://localhost:8000/api/incidents/INCIDENT_ID/remediate \
  -H "Content-Type: application/json" \
  -d '{"parameters":{"auto_scaling_group_name":"api-asg","desired_capacity":4},"estimated_monthly_cost_delta_usd":80}'
```

## Example: DynamoDB provisioned throughput

```shell
curl -X POST http://localhost:8000/api/incidents/INCIDENT_ID/remediate \
  -H "Content-Type: application/json" \
  -d '{"parameters":{"table_name":"orders","read_capacity_units":200,"write_capacity_units":100},"estimated_monthly_cost_delta_usd":60}'
```

Tables in on-demand (`PAY_PER_REQUEST`) mode are rejected because they do not
have provisioned RCU/WCU settings.

## Example: RDS storage

Increase only the storage autoscaling ceiling:

```shell
curl -X POST http://localhost:8000/api/incidents/INCIDENT_ID/remediate \
  -H "Content-Type: application/json" \
  -d '{"parameters":{"db_instance_identifier":"orders-db","max_allocated_storage_gib":500},"estimated_monthly_cost_delta_usd":40}'
```

The previous autoscaling ceiling can be restored while it remains above the
allocated storage. Directly increasing `allocated_storage_gib` cannot be
automatically reversed and is marked accordingly in the audit output.

## Example: RDS compute with approval

```shell
curl -X POST http://localhost:8000/api/incidents/INCIDENT_ID/remediate \
  -H "Content-Type: application/json" \
  -d '{"parameters":{"db_instance_identifier":"orders-db","db_instance_class":"db.r6g.large","apply_immediately":false},"approved_by":"operator@example.com","estimated_monthly_cost_delta_usd":180}'
```

Omitting `approved_by` returns HTTP 403. `apply_immediately=false` schedules the
class change for the maintenance window because changing compute class can
cause downtime.

## Verification and rollback

Each runbook records its verification metric in the execution. Submit the
matching post-change observation, for example:

```shell
curl -X POST http://localhost:8000/api/incidents/INCIDENT_ID/verify \
  -H "Content-Type: application/json" \
  -d '{"metric_name":"CPUUtilization","value":55}'
```

To restore the previous reversible state, use the execution ID returned in the
incident response:

```shell
curl -X POST http://localhost:8000/api/incidents/INCIDENT_ID/rollback \
  -H "Content-Type: application/json" \
  -d '{"execution_id":"EXECUTION_ID","approved_by":"operator@example.com"}'
```

Approval is required again when rolling back RDS compute. A rollback marks the
incident `ESCALATED` so an operator verifies the resulting service state.
