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

Two local vertical scenarios are implemented:

- `CPU saturation -> OPEN -> scale_service -> VERIFYING -> RESOLVED`
- `Faulty Service -> Prometheus -> Alertmanager -> webhook -> LocalStack SQS
  -> incident worker -> PostgreSQL`

The event path uses strict CloudEvents, stable delivery idempotency, an SQS
dead-letter queue, atomic incident/event persistence, and worker health and
Prometheus metrics. Remediation remains simulated. LangGraph, LLMs, Bedrock,
the dashboard, Terraform, and real AWS executors remain intentionally out of
scope.

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
```

If PowerShell script execution is disabled, open an activated Command Prompt
with `cmd /k .venv\Scripts\activate.bat`, then run the same commands there.

Services:

- CloudOps API: `http://localhost:8000`
- Faulty service: `http://localhost:8001`
- Incident worker health and metrics: `http://localhost:8002`
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

## Event-driven CPU detection

Start a bounded CPU fault and let the monitoring pipeline create the incident:

```shell
curl -X POST "http://localhost:8001/chaos/cpu?duration_seconds=45"
```

Prometheus fires `DemoServiceHighCPU` after 15 seconds. Alertmanager posts to
the CloudOps webhook, which publishes a normalized event to LocalStack SQS.
The incident worker validates and consumes it, then atomically creates or
correlates the incident and records `processed_events` in PostgreSQL.
