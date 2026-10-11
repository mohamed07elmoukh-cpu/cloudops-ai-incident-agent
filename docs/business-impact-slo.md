# Business impact and SLO assessment

The business-impact engine connects infrastructure incidents to a service-level
objective. The default demonstration profile maps resources containing
`checkout`, `orders`, or `api-production` to the critical **Commandes** service:

```text
Business traffic: 240 transactions/minute
Availability SLO: 99.9%
Rolling window: 30 days
Monthly error budget: 43.2 minutes
```

The assessment is calculated at request time so active outage duration and
remaining error budget continue to evolve. It is available from:

```text
GET /api/business-impact
GET /api/incidents/{incident_id}/business-impact
```

## Calculations

Availability uses the union of incident intervals inside the rolling window:

```text
availability = 1 - unavailable_minutes / window_minutes
error_budget = window_minutes * (1 - SLO_target)
remaining_budget = max(0, error_budget - unavailable_minutes)
burn_rate = unavailable_minutes / error_budget
```

Overlapping EC2, DynamoDB, and RDS incidents in one correlated service are
merged before unavailable time is summed. This prevents one application outage
from being counted once per affected AWS resource.

When a service has an active incident, its configured transaction rate is
reported as traffic **at risk**, not as confirmed lost transactions. The API
returns this distinction in its assumptions.

## Time to saturation

When at least two observations exist for the latest incident metric, the engine
uses the observed direction and rate of change. With only one observation, it
uses a conservative projection based on the distance beyond the alert threshold.
The response identifies the method as `observed_trend`,
`conservative_projection`, or `unavailable` so the dashboard never presents an
assumption as measured fact.

The assessment is intentionally deterministic and explainable. Production
service profiles can be injected through `BusinessImpactService` with their own
transaction volume, SLO, window, criticality, and resource patterns.
