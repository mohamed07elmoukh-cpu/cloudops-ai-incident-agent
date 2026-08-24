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

