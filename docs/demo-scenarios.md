# Demo scenarios

## CPU saturation (implemented locally)

Submit a CPU value above 85 percent to create a correlated `CPU_SATURATION`
incident. Execute the simulated `scale_service` runbook, then submit a CPU value
below 70 percent to move the incident from `OPEN` through `VERIFYING` to
`RESOLVED`.

## Unhealthy ECS task

Inject repeated application failures, correlate CloudWatch alerts, diagnose the
unhealthy task, request approval, replace it, and verify service stability.

## SQS backlog

Increase queue depth, identify insufficient consumer capacity, scale the worker
service through a guarded runbook, and verify that the backlog decreases.

## Faulty ECS deployment

Deploy a faulty task definition, correlate elevated error rate with the recent
deployment, approve a rollback, and confirm recovery of the service SLO.
