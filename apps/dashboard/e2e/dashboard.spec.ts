import { expect, test, type Page } from "@playwright/test";

import type { Incident } from "@/lib/types";

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
  remediation_attempted: false,
  verification_failures: 0,
  evidence: [{ incident_id: "20662f5b-cf00-4f7e-a3b6-d59570e41800", metric_name: "cpu_usage_percent", metric_value: 92, threshold: 85, timestamp: "2026-09-02T20:00:00Z", raw_data: {} }],
  remediation_executions: [],
};

async function mockDashboardApi(page: Page) {
  await page.route("**/backend/api/statistics", (route) => route.fulfill({ json: { total: 3, open: 1, resolved: 2, escalated: 0, active: 1, average_resolution_seconds: 95, by_status: { OPEN: 1, RESOLVED: 2 }, by_severity: { HIGH: 1, MEDIUM: 2 }, daily_trend: Array.from({ length: 14 }, (_, index) => ({ date: new Date(Date.UTC(2026, 7, 20 + index)).toISOString().slice(0, 10), detected: index === 13 ? 1 : 0, resolved: 0 })) } }));
  await page.route("**/backend/api/incidents?*", (route) => route.fulfill({ headers: { "X-Total-Count": "1", "X-Page": "1", "X-Page-Size": "20" }, json: [incident] }));
  await page.route("**/backend/api/system/health", (route) => route.fulfill({ json: { status: "healthy", checked_at: "2026-09-02T20:01:00Z", components: { api: { status: "healthy" }, postgresql: { status: "healthy" }, sqs: { status: "healthy", visible_messages: 0, in_flight_messages: 0 }, worker: { status: "healthy" } } } }));
}

test("affiche une vue opérationnelle claire", async ({ page }) => {
  await mockDashboardApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Centre de contrôle" })).toBeVisible();
  await expect(page.getByText("Incidents actifs")).toBeVisible();
  await expect(page.getByText("Opérationnel", { exact: true })).toBeVisible();
  await expect(page.getByText(incident.title)).toBeVisible();
  await page.screenshot({ path: "test-results/dashboard-preview.png", fullPage: true });
});

test("filtre les incidents et ouvre leur détail", async ({ page }) => {
  await mockDashboardApi(page);
  await page.route(`**/backend/api/incidents/${incident.id}`, (route) => route.fulfill({ json: incident }));
  await page.route(`**/backend/api/incidents/${incident.id}/events`, (route) => route.fulfill({ json: [] }));
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
  let current: Incident = { ...incident };
  await page.route(new RegExp(`/backend/api/incidents/${incident.id}$`), (route) =>
    route.fulfill({ json: current }),
  );
  await page.route(`**/backend/api/incidents/${incident.id}/events`, (route) =>
    route.fulfill({ json: [] }),
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
