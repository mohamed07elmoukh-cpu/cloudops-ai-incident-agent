# Threat model

Initial controls:

- least-privilege IAM roles for every executor;
- explicit allowlists for resources and remediation actions;
- mandatory approval for high-risk or destructive actions;
- immutable audit records for evidence, decisions, and executions;
- input validation for alerts, runbooks, and model-generated arguments;
- post-action verification and bounded rollback procedures;
- protection against prompt injection in logs and external evidence.

Implemented remediation controls:

- real AWS mutations are disabled unless `REMEDIATION_MODE=aws` is explicitly
  configured;
- the AWS adapter exposes only four capacity-increase actions and their bounded
  rollback operations;
- every AWS request requires an estimated monthly cost increase below both the
  global and runbook ceilings;
- per-resource cooldowns and idempotency keys prevent repeated scaling loops;
- RDS compute scaling and rollback require a recorded human approver;
- RDS allocated-storage changes are marked irreversible instead of pretending
  that an unsafe automatic rollback exists.

Production deployment still requires authenticated API callers, a trusted
server-side pricing source for cost estimates, and IAM policies restricted to
explicit resource ARNs. The request body currently carries the cost estimate
and approver identity, so these values must only come from a trusted control
plane rather than directly from an untrusted user.
