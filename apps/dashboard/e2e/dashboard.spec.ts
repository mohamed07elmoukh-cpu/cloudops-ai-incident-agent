import { expect, test, type Page } from "@playwright/test";

import type { BusinessImpact, Incident, LiveMetrics } from "@/lib/types";

const incident: Incident = {
  id: "20662f5b-cf00-4f7e-a3b6-d59570e41800",
  source: "demo-service",
  incident_type: "CPU_SATURATION",
  severity: "HIGH",
  status: "OPEN",
  title: "Saturation CPU détectée sur demo-service",
  description: "Le CPU a dépassé le seuil configuré.",
  detected_at: "2026-09-02T20:00:00Z",
  resolved_at: null,
  correlation_key: "demo-service:cpu-saturation",
  correlation_group: null,
  diagnosis_summary: null,
  probable_root_cause: null,
  diagnosis_confidence: null,
  diagnosis_evidence: [],
  diagnosed_at: null,
  remediation_attempted: false,
  verification_failures: 0,
  evidence: [{ incident_id: "20662f5b-cf00-4f7e-a3b6-d59570e41800", metric_name: "cpu_usage_percent", metric_value: 92, threshold: 85, timestamp: "2026-09-02T20:00:00Z", raw_data: {} }],
  remediation_executions: [],
};

const businessImpact: BusinessImpact = {
  service_key: "service:checkout",
  service_name: "Commandes",
  criticality: "critical",
  transactions_per_minute: 240,
  transactions_at_risk_per_minute: 240,
  slo_target_percent: 99.9,
  slo_window_days: 30,
  window_started_at: "2026-08-03T20:00:00Z",
  assessed_at: "2026-09-02T20:00:00Z",
  availability_percent: 99.98,
  error_budget_total_minutes: 43.2,
  error_budget_consumed_minutes: 8.5,
  error_budget_remaining_minutes: 34.7,
  error_budget_remaining_percent: 80.32,
  error_budget_burn_rate: 0.2,
  status: "at_risk",
  active_incidents: 1,
  affected_resources: ["orders-db"],
  time_to_saturation_minutes: 18,
  saturation_metric: "FreeStorageSpace",
  saturation_method: "observed_trend",
  summary: "L’incident RDS menace le service Commandes et 240 transactions/minute.",
  assumptions: [],
};

const metricTimes = Array.from({ length: 8 }, (_, index) =>
  new Date(Date.UTC(2026, 8, 2, 19, 53 + index)).toISOString(),
);

const liveMetrics: LiveMetrics = {
  mode: "demo",
  region: "us-east-1",
  generated_at: "2026-09-02T20:00:00Z",
  window_minutes: 60,
  period_seconds: 60,
  refresh_seconds: 8,
  resources: [
    {
      resource_type: "EC2", resource_id: "api-production-asg", title: "Amazon EC2", subtitle: "Auto Scaling Group", status: "healthy", metadata: {},
      series: [
        { key: "cpu", label: "CPU", unit: "%", color: "#0b57d0" },
        { key: "in_service", label: "Instances actives", unit: "instances", color: "#137333" },
        { key: "desired", label: "Capacité désirée", unit: "instances", color: "#9334e6" },
      ],
      points: metricTimes.map((timestamp, index) => ({ timestamp, values: { cpu: 48 + index, in_service: 3, desired: 4 } })),
      markers: [{ timestamp: metricTimes[3], kind: "remediation", label: "Capacité augmentée", incident_id: null, source: "demo" }],
    },
    {
      resource_type: "DYNAMODB", resource_id: "orders", title: "Amazon DynamoDB", subtitle: "Table provisionnée", status: "healthy", metadata: {},
      series: [
        { key: "consumed_read", label: "RCU consommées", unit: "RCU", color: "#0b57d0" },
        { key: "provisioned_read", label: "RCU provisionnées", unit: "RCU", color: "#137333" },
        { key: "consumed_write", label: "WCU consommées", unit: "WCU", color: "#a142f4" },
        { key: "provisioned_write", label: "WCU provisionnées", unit: "WCU", color: "#f9ab00" },
        { key: "throttles", label: "Requêtes limitées", unit: "requêtes", color: "#d93025" },
      ],
      points: metricTimes.map((timestamp, index) => ({ timestamp, values: { consumed_read: 120 + index, provisioned_read: 200, consumed_write: 60 + index, provisioned_write: 100, throttles: 0 } })),
      markers: [],
    },
    {
      resource_type: "RDS", resource_id: "orders-db", title: "Amazon RDS", subtitle: "Instance de base de données", status: "healthy", metadata: { instance_class: "db.r6g.large" },
      series: [
        { key: "cpu", label: "CPU", unit: "%", color: "#0b57d0" },
        { key: "free_storage_gib", label: "Stockage libre", unit: "GiB", color: "#137333" },
        { key: "connections", label: "Connexions", unit: "conn.", color: "#a142f4" },
      ],
      points: metricTimes.map((timestamp, index) => ({ timestamp, values: { cpu: 42 + index, free_storage_gib: 32, connections: 80 + index } })),
      markers: [],
    },
  ],
};

async function mockDashboardApi(page: Page) {
  await page.route("**/backend/api/statistics", (route) => route.fulfill({ json: { total: 3, open: 1, resolved: 2, escalated: 0, active: 1, average_resolution_seconds: 95, by_status: { OPEN: 1, RESOLVED: 2 }, by_severity: { HIGH: 1, MEDIUM: 2 }, daily_trend: Array.from({ length: 14 }, (_, index) => ({ date: new Date(Date.UTC(2026, 7, 20 + index)).toISOString().slice(0, 10), detected: index === 13 ? 1 : 0, resolved: 0 })) } }));
  await page.route("**/backend/api/incidents?*", (route) => route.fulfill({ headers: { "X-Total-Count": "1", "X-Page": "1", "X-Page-Size": "20" }, json: [incident] }));
  await page.route("**/backend/api/system/health", (route) => route.fulfill({ json: { status: "healthy", checked_at: "2026-09-02T20:01:00Z", components: { api: { status: "healthy" }, postgresql: { status: "healthy" }, sqs: { status: "healthy", visible_messages: 0, in_flight_messages: 0 }, worker: { status: "healthy" } } } }));
  await page.route("**/backend/api/metrics/live?*", (route) => route.fulfill({ json: liveMetrics }));
  await page.route("**/backend/api/business-impact", (route) => route.fulfill({ json: { assessed_at: businessImpact.assessed_at, total_transactions_at_risk_per_minute: 240, services_at_risk: 1, services: [businessImpact] } }));
}

async function mockIncidentBusinessImpact(page: Page) {
  await page.route("**/backend/api/incidents/*/business-impact", (route) =>
    route.fulfill({ json: businessImpact }),
  );
}

test("affiche une vue opérationnelle claire", async ({ page }) => {
  await mockDashboardApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Centre de contrôle" })).toBeVisible();
  await expect(page.getByText("Incidents actifs")).toBeVisible();
  await expect(page.getByText("Opérationnel", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Capacité de l’infrastructure" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Amazon EC2" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Amazon DynamoDB" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Amazon RDS" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Commandes" })).toBeVisible();
  await expect(page.getByText("240 txn/min")).toBeVisible();
  await expect(page.getByText(incident.title)).toBeVisible();
  await page.screenshot({ path: "test-results/dashboard-preview.png", fullPage: true });
});

test("filtre les incidents et ouvre leur détail", async ({ page }) => {
  await mockDashboardApi(page);
  await mockIncidentBusinessImpact(page);
  await page.route(`**/backend/api/incidents/${incident.id}`, (route) => route.fulfill({ json: incident }));
  await page.route(`**/backend/api/incidents/${incident.id}/events`, (route) => route.fulfill({ json: [] }));
  await page.route(`**/backend/api/incidents/${incident.id}/correlated`, (route) => route.fulfill({ json: [incident] }));
  await page.route(`**/backend/api/incidents/${incident.id}/timeline`, (route) => route.fulfill({ json: [{ timestamp: incident.detected_at, kind: "incident", title: "Incident détecté", status: "OPEN", detail: { source: "demo-service" } }] }));
  await page.goto("/incidents");
  await expect(page.getByRole("heading", { name: "Incidents" })).toBeVisible();
  await page.getByLabel("Filtrer par statut").selectOption("OPEN");
  await page.getByText(incident.title).click();
  await expect(page.getByRole("heading", { name: incident.title })).toBeVisible();
  await expect(page.getByText("scale_service", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("cpu_usage_percent")).toBeVisible();
});

test("confirme la remédiation puis résout l’incident", async ({ page }) => {
  await mockIncidentBusinessImpact(page);
  let current: Incident = { ...incident };
  await page.route(new RegExp(`/backend/api/incidents/${incident.id}$`), (route) =>
    route.fulfill({ json: current }),
  );
  await page.route(`**/backend/api/incidents/${incident.id}/events`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/backend/api/incidents/${incident.id}/correlated`, (route) =>
    route.fulfill({ json: [current] }),
  );
  await page.route(`**/backend/api/incidents/${incident.id}/timeline`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/backend/api/incidents/${incident.id}/remediate`, (route) => {
    current = {
      ...current,
      status: "VERIFYING",
      remediation_attempted: true,
      remediation_executions: [
        {
          id: "5a8c711c-55d3-4c5d-a868-d531be85cdd4",
          incident_id: incident.id,
          runbook_name: "scale_service",
          status: "VERIFYING",
          started_at: "2026-09-02T20:02:00Z",
          completed_at: null,
          output: {},
          idempotency_key: `${incident.id}:scale_service:1.0`,
        },
      ],
    };
    return route.fulfill({ json: current });
  });
  await page.route(`**/backend/api/incidents/${incident.id}/verify`, (route) => {
    current = { ...current, status: "RESOLVED", resolved_at: "2026-09-02T20:03:00Z" };
    return route.fulfill({ json: current });
  });

  await page.goto(`/incidents/${incident.id}`);
  await page.getByRole("button", { name: "Lancer le runbook" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Confirmer" }).click();
  await expect(page.getByText("Vérification", { exact: true })).toBeVisible();
  await page.getByLabel("Valeur CPU de vérification").fill("55");
  await page.getByRole("button", { name: "Vérifier" }).click();
  await expect(page.getByText("Résolu", { exact: true })).toBeVisible();
});

test("configure une mise à l’échelle EC2 avec garde-fou de coût", async ({ page }) => {
  await mockIncidentBusinessImpact(page);
  const ec2Incident: Incident = {
    ...incident,
    source: "api-asg",
    incident_type: "EC2_CAPACITY_SATURATION",
    title: "Saturation de la capacité EC2",
  };
  let currentEc2Incident = ec2Incident;
  await page.route(new RegExp(`/backend/api/incidents/${incident.id}$`), (route) =>
    route.fulfill({ json: currentEc2Incident }),
  );
  await page.route(`**/backend/api/incidents/${incident.id}/events`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/backend/api/incidents/${incident.id}/timeline`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/backend/api/incidents/${incident.id}/remediate`, async (route) => {
    const request = route.request().postDataJSON();
    expect(request.runbook_name).toBe("scale_ec2_auto_scaling_group");
    expect(request.parameters).toEqual({
      auto_scaling_group_name: "api-asg",
      desired_capacity: 4,
    });
    expect(request.estimated_monthly_cost_delta_usd).toBe(75);
    currentEc2Incident = { ...ec2Incident, status: "VERIFYING" };
    await route.fulfill({ json: currentEc2Incident });
  });

  await page.goto(`/incidents/${incident.id}`);
  await expect(page.getByRole("heading", { name: "Remédiation AWS" })).toBeVisible();
  await page.getByLabel("Capacité désirée").fill("4");
  await page.getByLabel("Coût mensuel supplémentaire estimé (USD)").fill("75");
  await page.getByRole("button", { name: "Lancer le runbook" }).click();
  await page.getByRole("button", { name: "Confirmer" }).click();
  await expect(page.getByText("Vérification", { exact: true })).toBeVisible();
});
