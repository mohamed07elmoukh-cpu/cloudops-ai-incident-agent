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

The resource-capacity endpoint also creates dedicated EC2, DynamoDB, RDS
storage, and RDS compute incidents. Declarative AWS runbooks pass through a
shared policy layer before the SDK adapter is invoked. The policy requires a
trusted monthly cost estimate, applies both global and runbook-specific cost
ceilings, prevents repeated changes during a resource cooldown, and records
the human approver required for RDS compute changes.

The AWS adapter reads the current resource state before every change. It keeps
the previous EC2 capacity, DynamoDB throughput, RDS storage limit, or RDS
instance class in the execution audit record. That state drives an explicit
rollback endpoint. Increasing allocated RDS storage is deliberately marked as
irreversible because AWS does not support decreasing it afterwards.

```text
Capacity signal -> typed incident -> policy gate -> simulated/AWS executor
                                          |                |
                                  cost + cooldown     previous state
                                  human approval          |
                                          |          verification
                                          +---------- rollback
```

The primary detection path is event-driven:

```text
Faulty Service -> Prometheus -> Alertmanager -> CloudOps webhook
               -> LocalStack SQS -> Incident Worker -> PostgreSQL

CloudWatch Alarm -> EventBridge rule -> AWS SQS
                                  -> Incident Worker -> PostgreSQL
```

The webhook validates Alertmanager notifications and publishes strict
`CloudEventEnvelope` messages without invoking domain detection. Delivery IDs
are stable per alert occurrence. The worker uses bounded SQS long polling,
delegates to the existing detection service, and deletes a message only after
the database transaction commits. That transaction includes both incident and
evidence changes and the unique `processed_events` marker. Failed messages are
left for SQS redrive to the DLQ after three receives.

In AWS, CloudWatch publishes alarm state changes to the default EventBridge
bus. A Terraform-managed rule selects `ALARM` transitions with the configured
alarm-name prefix and targets the incident queue. The queue resource policy is
restricted to that rule ARN. The worker distinguishes raw EventBridge messages
from internal CloudEvents, normalizes supported EC2, DynamoDB, and RDS metrics,
and then uses the same transactional and idempotent processor. EventBridge
delivery failures and worker processing failures use separate DLQs so their
causes remain operationally distinguishable.

## Full-stack operations surface

The dashboard is a Next.js application that communicates with FastAPI through
a same-origin server-side proxy. TanStack Query refreshes operational data at a
five-second interval, while Recharts renders aggregate trends. The UI can list
and filter incidents, inspect evidence and processed events, display a combined
timeline, execute the simulated runbook, and submit a verification signal.

FastAPI exposes dashboard-oriented read models without leaking SQLAlchemy
entities: filtered incident lists with pagination headers, statistics, event
history, incident timelines, and aggregated component health. The dashboard is
packaged as a standalone Node.js Docker image on the same dedicated network.
