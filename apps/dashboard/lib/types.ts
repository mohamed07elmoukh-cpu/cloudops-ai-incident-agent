export type IncidentStatus =
  | "OPEN"
  | "INVESTIGATING"
  | "REMEDIATING"
  | "VERIFYING"
  | "RESOLVED"
  | "FAILED"
  | "ESCALATED";

export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface Evidence {
  incident_id: string;
  metric_name: string;
  metric_value: number;
  threshold: number;
  timestamp: string;
  raw_data: Record<string, unknown>;
}

export interface RemediationExecution {
  id: string;
  incident_id: string;
  runbook_name: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  output: Record<string, unknown>;
  idempotency_key: string;
}

export interface RemediationRequest {
  runbook_name?: string;
  idempotency_key?: string;
  parameters?: Record<string, string | number | boolean | null>;
  approved_by?: string;
  estimated_monthly_cost_delta_usd?: number;
}

export interface CostEstimate {
  monthly_delta_usd: number;
  currency: string;
  source: string;
  assumptions: string[];
  line_items: Array<Record<string, unknown>>;
}

export interface Incident {
  id: string;
  source: string;
  incident_type: string;
  severity: Severity;
  status: IncidentStatus;
  title: string;
  description: string;
  detected_at: string;
  resolved_at: string | null;
  correlation_key: string;
  correlation_group: string | null;
  diagnosis_summary: string | null;
  probable_root_cause: string | null;
  diagnosis_confidence: number | null;
  diagnosis_evidence: Array<Record<string, unknown>>;
  diagnosed_at: string | null;
  remediation_attempted: boolean;
  verification_failures: number;
  evidence: Evidence[];
  remediation_executions: RemediationExecution[];
}

export interface ProcessedEvent {
  event_id: string;
  event_type: string;
  processed_at: string;
  incident_id: string | null;
  status: string;
  trace_id: string;
  published_at: string | null;
  message_id: string | null;
}

export interface TimelineEntry {
  timestamp: string;
  kind: "incident" | "evidence" | "event" | "remediation";
  title: string;
  status: string | null;
  detail: Record<string, unknown>;
}

export interface DailyIncidentPoint {
  date: string;
  detected: number;
  resolved: number;
}

export interface Statistics {
  total: number;
  open: number;
  resolved: number;
  escalated: number;
  active: number;
  average_resolution_seconds: number | null;
  by_status: Record<string, number>;
  by_severity: Record<string, number>;
  daily_trend: DailyIncidentPoint[];
}

export type CloudResourceType = "EC2" | "DYNAMODB" | "RDS";

export interface LiveMetricSeries {
  key: string;
  label: string;
  unit: string;
  color: string;
}

export interface LiveMetricPoint {
  timestamp: string;
  values: Record<string, number>;
}

export interface LiveMetricMarker {
  timestamp: string;
  kind: "detection" | "remediation" | "rollback";
  label: string;
  incident_id: string | null;
  source: "audit" | "demo";
}

export interface LiveResourceMetrics {
  resource_type: CloudResourceType;
  resource_id: string;
  title: string;
  subtitle: string;
  status: "healthy" | "attention";
  metadata: Record<string, string>;
  series: LiveMetricSeries[];
  points: LiveMetricPoint[];
  markers: LiveMetricMarker[];
}

export interface LiveMetrics {
  mode: "aws" | "demo";
  region: string;
  generated_at: string;
  window_minutes: number;
  period_seconds: number;
  refresh_seconds: number;
  resources: LiveResourceMetrics[];
}

export interface ComponentHealth {
  status: "healthy" | "unhealthy";
  detail: string | null;
  visible_messages: number | null;
  in_flight_messages: number | null;
}

export interface SystemHealth {
  status: "healthy" | "degraded";
  checked_at: string;
  components: Record<string, ComponentHealth>;
}

export interface IncidentFilters {
  status?: string;
  severity?: string;
  source?: string;
  incident_type?: string;
  search?: string;
  page?: number;
  page_size?: number;
  sort?: "newest" | "oldest";
}

export interface IncidentPage {
  items: Incident[];
  total: number;
  page: number;
  pageSize: number;
}
