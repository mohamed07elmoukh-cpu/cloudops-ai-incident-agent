import { ArrowRight, Inbox } from "lucide-react";
import Link from "next/link";

import { formatDate } from "@/lib/api";
import type { Incident } from "@/lib/types";

import { SeverityBadge, StatusBadge } from "./badges";

export function IncidentTable({ incidents }: { incidents: Incident[] }) {
  if (!incidents.length) {
    return (
      <div className="empty-state">
        <Inbox size={27} />
        <strong>Aucun incident trouvé</strong>
        <p>Les nouveaux incidents apparaîtront ici dès leur détection.</p>
      </div>
    );
  }
  return (
    <div className="table-scroll">
      <table>
        <thead><tr><th>Incident</th><th>Sévérité</th><th>Statut</th><th>Source</th><th>Détection</th><th aria-label="Action" /></tr></thead>
        <tbody>
          {incidents.map((incident) => (
            <tr key={incident.id}>
              <td className="incident-cell">
                <Link href={`/incidents/${incident.id}`}>{incident.title}</Link>
                <span>{incident.id.slice(0, 8)} · {incident.incident_type}</span>
              </td>
              <td><SeverityBadge severity={incident.severity} /></td>
              <td><StatusBadge status={incident.status} /></td>
              <td className="mono muted">{incident.source}</td>
              <td className="muted">{formatDate(incident.detected_at)}</td>
              <td><Link className="text-link" href={`/incidents/${incident.id}`} aria-label={`Voir ${incident.title}`}><ArrowRight size={17} /></Link></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
