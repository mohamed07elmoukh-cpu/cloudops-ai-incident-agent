import type {
  Incident,
  IncidentFilters,
  IncidentPage,
  ProcessedEvent,
  RemediationRequest,
  Statistics,
  SystemHealth,
  TimelineEntry,
} from "@/lib/types";

const API_PREFIX = "/backend/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "Erreur inattendue" }));
    throw new Error(payload.detail ?? `Erreur HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function getIncidents(filters: IncidentFilters = {}): Promise<IncidentPage> {
  const parameters = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== "") parameters.set(key, String(value));
  });
  const response = await fetch(`${API_PREFIX}/incidents?${parameters.toString()}`);
  if (!response.ok) throw new Error("Impossible de charger les incidents");
  const items = (await response.json()) as Incident[];
  return {
    items,
    total: Number(response.headers.get("X-Total-Count") ?? items.length),
    page: Number(response.headers.get("X-Page") ?? filters.page ?? 1),
    pageSize: Number(response.headers.get("X-Page-Size") ?? filters.page_size ?? 20),
  };
}

export const getIncident = (id: string) => request<Incident>(`/incidents/${id}`);
export const getIncidentEvents = (id: string) =>
  request<ProcessedEvent[]>(`/incidents/${id}/events`);
export const getIncidentTimeline = (id: string) =>
  request<TimelineEntry[]>(`/incidents/${id}/timeline`);
export const getStatistics = () => request<Statistics>("/statistics");
export async function getSystemHealth(): Promise<SystemHealth> {
  const response = await fetch(`${API_PREFIX}/system/health`, { cache: "no-store" });
  if (response.status !== 200 && response.status !== 503) {
    throw new Error("Impossible de charger l’état du système");
  }
  return response.json() as Promise<SystemHealth>;
}

export const remediateIncident = (
  id: string,
  remediation: RemediationRequest = { runbook_name: "scale_service" },
) =>
  request<Incident>(`/incidents/${id}/remediate`, {
    method: "POST",
    body: JSON.stringify(remediation),
  });

export const verifyIncident = (id: string, value: number, metricName = "cpu_usage_percent") =>
  request<Incident>(`/incidents/${id}/verify`, {
    method: "POST",
    body: JSON.stringify({ value, metric_name: metricName }),
  });

export const rollbackRemediation = (id: string, executionId: string, approvedBy?: string) =>
  request<Incident>(`/incidents/${id}/rollback`, {
    method: "POST",
    body: JSON.stringify({ execution_id: executionId, approved_by: approvedBy }),
  });

export function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}
