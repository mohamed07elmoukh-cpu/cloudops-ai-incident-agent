import type { IncidentStatus, Severity } from "@/lib/types";

const statusLabels: Record<IncidentStatus, string> = {
  OPEN: "Ouvert",
  INVESTIGATING: "Investigation",
  REMEDIATING: "Remédiation",
  VERIFYING: "Vérification",
  RESOLVED: "Résolu",
  FAILED: "Échec",
  ESCALATED: "Escaladé",
};

export function StatusBadge({ status }: { status: IncidentStatus }) {
  return <span className={`badge ${status.toLowerCase()}`}>{statusLabels[status]}</span>;
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={`severity-badge ${severity.toLowerCase()}`}>{severity}</span>;
}
