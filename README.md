# CloudOps AI Incident Agent

AI-powered AWS incident detection, root-cause analysis, and policy-guarded
autonomous remediation.

## Objectives

- Detect cloud anomalies and correlate related alerts.
- Collect metrics, logs, traces, and recent changes.
- Identify a probable root cause with AI-assisted analysis.
- Select a remediation runbook and evaluate safety policies.
- Execute automatically or request human approval.
- Verify actual service recovery.
- Produce a complete, auditable incident report.

## Project layout

- `apps/`: FastAPI API, SQS incident worker, and incident dashboard.
- `cloudops_agent/`: detection, diagnosis, orchestration, policies, remediation,
  verification, and infrastructure adapters.
- `runbooks/`: versioned remediation procedures.
- `demo/`: faulty service and controlled fault injection.
- `observability/`: Prometheus, Grafana, and OpenTelemetry configuration.
- `infrastructure/terraform/`: reusable modules and demo environments.
- `tests/`: unit, contract, integration, end-to-end, chaos, security, and agent
  evaluation suites.
- `docs/`: architecture, threat model, and demo scenarios.

## Status

The following vertical capabilities are implemented:

- `CPU saturation -> OPEN -> scale_service -> VERIFYING -> RESOLVED`
- `Faulty Service -> Prometheus -> Alertmanager -> webhook -> LocalStack SQS
  -> incident worker -> PostgreSQL`
- `CloudWatch Alarm -> EventBridge -> AWS SQS -> incident worker -> PostgreSQL`
- A responsive Next.js operations dashboard for incident monitoring,
  remediation, verification, event timelines, and platform health.
- Policy-guarded EC2 Auto Scaling, provisioned DynamoDB throughput, RDS
  storage, and RDS compute runbooks. They run in safe simulation mode by
  default and can use the real AWS SDK adapter when explicitly enabled.

The event path uses strict CloudEvents, stable delivery idempotency, an SQS
dead-letter queue, atomic incident/event persistence, and worker health and
Prometheus metrics. AWS capacity actions enforce an estimated monthly cost
ceiling, a per-resource cooldown, idempotency, verification, and rollback.
RDS compute changes additionally require a recorded human approver. A
deployable Terraform stack now provisions the native CloudWatch/EventBridge
delivery path, its SQS queues, DLQs, resource policies, and worker IAM policy.
LangGraph, LLMs, and Bedrock remain out of scope.

## Local startup

```shell
python -m venv .venv
# PowerShell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

docker compose config
docker compose up -d --build
pytest -q
ruff check .
mypy .
npm --prefix apps/dashboard run lint
npm --prefix apps/dashboard run typecheck
npm --prefix apps/dashboard run test:e2e
```

If PowerShell script execution is disabled, open an activated Command Prompt
with `cmd /k .venv\Scripts\activate.bat`, then run the same commands there.

Services:

- CloudOps API: `http://localhost:8000`
- Faulty service: `http://localhost:8001`
- Incident worker health and metrics: `http://localhost:8002`
- Operations dashboard: `http://localhost:3000`
- Prometheus: `http://localhost:9090`
- Alertmanager: `http://localhost:9093`
- LocalStack: `http://localhost:4567`
- PostgreSQL: `localhost:55432`

## CPU saturation scenario

Create an incident:

```shell
curl -X POST http://localhost:8000/api/detection/evaluate \
  -H "Content-Type: application/json" \
  -d '{"source":"demo-service","metric_name":"cpu_usage_percent","value":92,"threshold":85,"timestamp":"2026-08-24T17:00:00Z"}'
```

Use the returned incident UUID to execute the selected runbook and verify
recovery:

```shell
curl -X POST http://localhost:8000/api/incidents/INCIDENT_ID/remediate \
  -H "Content-Type: application/json" -d '{}'
curl -X POST http://localhost:8000/api/incidents/INCIDENT_ID/verify \
  -H "Content-Type: application/json" -d '{"value":55}'
```

The final incident status is `RESOLVED`, and its remediation execution is
`SUCCEEDED`.

## AWS capacity remediation

The resource detection endpoint creates four dedicated incident types and
selects the corresponding runbook:

- `EC2_CAPACITY_SATURATION` -> increase an Auto Scaling Group desired capacity;
- `DYNAMODB_CAPACITY_SATURATION` -> increase provisioned RCU/WCU;
- `RDS_STORAGE_LOW` -> increase allocated storage or its autoscaling limit;
- `RDS_COMPUTE_SATURATION` -> change DB instance class after human approval.

All AWS runbooks are simulated unless `REMEDIATION_MODE=aws` is set. Real mode
requires a least-privilege AWS identity and never uses `AWS_ENDPOINT_URL`,
which remains reserved for the local SQS pipeline. See
[`docs/aws-remediation.md`](docs/aws-remediation.md) for API examples, IAM
permissions, safety constraints, rollback behavior, and production caveats.

## Event-driven CPU detection

Start a bounded CPU fault and let the monitoring pipeline create the incident:

```shell
curl -X POST "http://localhost:8001/chaos/cpu?duration_seconds=45"
```

Prometheus fires `DemoServiceHighCPU` after 15 seconds. Alertmanager posts to
the CloudOps webhook, which publishes a normalized event to LocalStack SQS.
The incident worker validates and consumes it, then atomically creates or
correlates the incident and records `processed_events` in PostgreSQL.

## Real CloudWatch/EventBridge connection

The production path consumes native CloudWatch alarm state-change messages;
no AWS webhook or polling process is required:

```text
CloudWatch Alarm (ALARM) -> EventBridge rule -> SQS -> incident worker
```

The rule forwards alarms whose names start with `cloudops-`. The worker maps
standard `AWS/EC2`, `AWS/DynamoDB`, and `AWS/RDS` metric dimensions to the
matching resource incidents while retaining the complete AWS event as audit
evidence. Deploy and test the stack using
[`docs/cloudwatch-eventbridge.md`](docs/cloudwatch-eventbridge.md).

## Operations dashboard

The Next.js dashboard refreshes every five seconds and provides:

- incident statistics and a 14-day trend;
- search, status and severity filters, sorting, and pagination;
- incident details, evidence, CloudEvents, and lifecycle timeline;
- guarded local and AWS capacity remediation, rollback, and metric verification;
- API, PostgreSQL, SQS, and worker health.
