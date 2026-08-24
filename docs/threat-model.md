# Threat model

Initial controls:

- least-privilege IAM roles for every executor;
- explicit allowlists for resources and remediation actions;
- mandatory approval for high-risk or destructive actions;
- immutable audit records for evidence, decisions, and executions;
- input validation for alerts, runbooks, and model-generated arguments;
- post-action verification and bounded rollback procedures;
- protection against prompt injection in logs and external evidence.

