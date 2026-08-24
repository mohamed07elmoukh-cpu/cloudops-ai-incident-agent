# Architecture

The platform follows an event-driven incident lifecycle:

1. Normalize and correlate monitoring alerts into incidents.
2. Collect metrics, logs, traces, and recent infrastructure changes.
3. Produce an evidence-backed probable root cause.
4. Select a versioned remediation runbook.
5. Evaluate safety policies and request approval when required.
6. Execute the remediation through a least-privilege AWS adapter.
7. Verify recovery using service-level signals.
8. Generate an auditable incident report.

The orchestration layer owns state transitions. AWS and local adapters keep the
domain logic testable without direct cloud access.

## Implemented local vertical slices

The manual diagnostic endpoint accepts CPU observations through the CloudOps
API. A value above its alert threshold creates one correlated
`CPU_SATURATION` incident and stores the observation as evidence. The API
selects the validated `scale_service` runbook and delegates it to an
allowlisted, idempotent simulated executor. No AWS call is made.

After execution, the incident waits in `VERIFYING`. A CPU value below 70 percent
resolves it; three unsuccessful checks escalate it. PostgreSQL stores the
incident, evidence, and remediation audit trail, with schema changes managed by
Alembic.

The primary detection path is event-driven:

```text
Faulty Service -> Prometheus -> Alertmanager -> CloudOps webhook
               -> LocalStack SQS -> Incident Worker -> PostgreSQL
```

The webhook validates Alertmanager notifications and publishes strict
`CloudEventEnvelope` messages without invoking domain detection. Delivery IDs
are stable per alert occurrence. The worker uses bounded SQS long polling,
delegates to the existing detection service, and deletes a message only after
the database transaction commits. That transaction includes both incident and
evidence changes and the unique `processed_events` marker. Failed messages are
left for SQS redrive to the DLQ after three receives.
