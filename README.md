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

The repository currently contains the initial project scaffold.
