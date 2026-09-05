# Real CloudWatch and EventBridge connection

## Architecture

```text
EC2 / DynamoDB / RDS metric
            -> CloudWatch Alarm enters ALARM
            -> default EventBridge event bus
            -> EventBridge rule
            -> incident SQS queue
            -> incident-worker
            -> PostgreSQL incident + original AWS evidence
```

There is no public webhook in this path. The Terraform stack creates the rule,
the queue, its resource policy, a least-privilege worker IAM policy, and two
separate dead-letter queues:

- `*-eventbridge-delivery-dlq` for delivery failures before SQS;
- `*-incidents-dlq` for messages the worker cannot process after five receives.

The rule accepts `ALARM` transitions whose names start with `cloudops-` by
default. The worker maps these standard dimensions:

| Namespace | Resource dimension | Incident |
| --- | --- | --- |
| `AWS/EC2` | `AutoScalingGroupName`, then `InstanceId` | EC2 capacity |
| `AWS/DynamoDB` | `TableName` | DynamoDB capacity |
| `AWS/RDS` | `DBInstanceIdentifier`, then `DBClusterIdentifier` | RDS storage or compute |

For EC2 automatic remediation, use `AutoScalingGroupName`. An `InstanceId`
alarm creates an incident, but the remediation request must then name its Auto
Scaling Group explicitly.

## 1. Deploy the AWS event path

Prerequisites are Terraform 1.6+, AWS permissions for EventBridge, SQS and IAM,
and CloudWatch alarms in the same region as the stack.

```powershell
Set-Location infrastructure/terraform/cloudwatch-eventbridge
Copy-Item terraform.tfvars.example terraform.tfvars
terraform init
terraform plan
terraform apply
terraform output
```

Edit `terraform.tfvars` first. `worker_role_name` can reference an existing ECS,
EKS, or EC2 workload role. If it is omitted, attach the `worker_policy_arn`
output to the role yourself.

## 2. Run the worker against AWS

Use a workload IAM role whenever possible. In that case, do not set static AWS
access keys. `AWS_ENDPOINT_URL` must also be absent because it is reserved for
LocalStack.

```powershell
$env:AWS_REGION = "eu-west-1"
$env:INCIDENT_QUEUE_URL = terraform output -raw incident_queue_url
$env:DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:5432/cloudops"
Remove-Item Env:AWS_ENDPOINT_URL -ErrorAction SilentlyContinue
alembic upgrade head
python apps/incident-worker/worker_main.py
```

For a local operator session, set `AWS_PROFILE` before starting the worker. Its
health and Prometheus endpoints are `http://localhost:8002/health` and
`http://localhost:8002/metrics`.

## 3. Create compatible alarms

EC2 Auto Scaling Group CPU example:

```powershell
aws cloudwatch put-metric-alarm `
  --alarm-name cloudops-api-asg-high-cpu `
  --namespace AWS/EC2 `
  --metric-name CPUUtilization `
  --dimensions Name=AutoScalingGroupName,Value=api-production-asg `
  --statistic Average `
  --period 60 `
  --evaluation-periods 2 `
  --datapoints-to-alarm 2 `
  --threshold 80 `
  --comparison-operator GreaterThanThreshold `
  --treat-missing-data notBreaching
```

DynamoDB provisioned-throughput example:

```powershell
aws cloudwatch put-metric-alarm `
  --alarm-name cloudops-orders-read-throttles `
  --namespace AWS/DynamoDB `
  --metric-name ReadThrottleEvents `
  --dimensions Name=TableName,Value=orders `
  --statistic Sum `
  --period 60 `
  --evaluation-periods 1 `
  --threshold 1 `
  --comparison-operator GreaterThanOrEqualToThreshold `
  --treat-missing-data notBreaching
```

RDS low-storage example (10 GiB in bytes):

```powershell
aws cloudwatch put-metric-alarm `
  --alarm-name cloudops-orders-db-low-storage `
  --namespace AWS/RDS `
  --metric-name FreeStorageSpace `
  --dimensions Name=DBInstanceIdentifier,Value=orders-db `
  --statistic Average `
  --period 300 `
  --evaluation-periods 2 `
  --datapoints-to-alarm 2 `
  --threshold 10737418240 `
  --comparison-operator LessThanThreshold `
  --treat-missing-data missing
```

## 4. Verify end to end

Cross a real alarm threshold, then inspect the queue, worker health, and API:

```powershell
aws sqs get-queue-attributes `
  --queue-url (terraform output -raw incident_queue_url) `
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible

Invoke-RestMethod http://localhost:8002/health
Invoke-RestMethod http://localhost:8000/api/incidents
```

The worker stores the complete EventBridge message in the incident evidence.
Replaying the same message is safe because its AWS event ID becomes the unique
`processed_events.event_id`.

An unsupported metric or an alarm event without an evaluated datapoint is not
acknowledged and eventually reaches the consumer DLQ. Inspect the EventBridge
DLQ for target-delivery problems and the consumer DLQ for normalization,
database, or worker failures.

## Cleanup

```powershell
terraform destroy
```

This removes the Terraform-managed queues and their messages. Export or redrive
messages that must be retained before cleanup.
