"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, RotateCcw, Search } from "lucide-react";
import { useState } from "react";

import { IncidentTable } from "@/components/incident-table";
import { getIncidents } from "@/lib/api";
import type { IncidentFilters } from "@/lib/types";

const initialFilters: IncidentFilters = { page: 1, page_size: 10, sort: "newest" };

export function IncidentsExplorer() {
  const [filters, setFilters] = useState<IncidentFilters>(initialFilters);
  const query = useQuery({
    queryKey: ["incidents", filters],
    queryFn: () => getIncidents(filters),
    refetchInterval: 5_000,
  });
  const update = (key: keyof IncidentFilters, value: string) =>
    setFilters((current) => ({ ...current, [key]: value || undefined, page: 1 }));
  const totalPages = Math.max(1, Math.ceil((query.data?.total ?? 0) / (filters.page_size ?? 10)));

  return <>
    <div className="page-heading"><div><span className="eyebrow">Gestion opérationnelle</span><h1>Incidents</h1><p>Recherchez, filtrez et suivez chaque incident depuis sa détection.</p></div><span className="last-updated">{query.data?.total ?? 0} résultat(s)</span></div>
    <section className="card table-shell">
      <div className="filters">
        <label className="field" aria-label="Rechercher"><Search size={15} /><input className="input" value={filters.search ?? ""} onChange={(event) => update("search", event.target.value)} placeholder="Rechercher un incident, une source…" /></label>
        <select className="select" aria-label="Filtrer par statut" value={filters.status ?? ""} onChange={(event) => update("status", event.target.value)}><option value="">Tous les statuts</option><option value="OPEN">Ouvert</option><option value="INVESTIGATING">Investigation</option><option value="REMEDIATING">Remédiation</option><option value="VERIFYING">Vérification</option><option value="RESOLVED">Résolu</option><option value="ESCALATED">Escaladé</option><option value="FAILED">Échec</option></select>
        <select className="select" aria-label="Filtrer par sévérité" value={filters.severity ?? ""} onChange={(event) => update("severity", event.target.value)}><option value="">Toutes sévérités</option><option value="CRITICAL">Critique</option><option value="HIGH">Haute</option><option value="MEDIUM">Moyenne</option><option value="LOW">Basse</option></select>
        <input className="input" aria-label="Filtrer par source" value={filters.source ?? ""} onChange={(event) => update("source", event.target.value)} placeholder="Source" />
        <select className="select" aria-label="Filtrer par type" value={filters.incident_type ?? ""} onChange={(event) => update("incident_type", event.target.value)}><option value="">Tous les types</option><option value="CPU_SATURATION">Saturation CPU locale</option><option value="EC2_CAPACITY_SATURATION">Capacité EC2</option><option value="DYNAMODB_CAPACITY_SATURATION">Capacité DynamoDB</option><option value="RDS_STORAGE_LOW">Stockage RDS</option><option value="RDS_COMPUTE_SATURATION">Compute RDS</option></select>
        <select className="select" aria-label="Trier les incidents" value={filters.sort ?? "newest"} onChange={(event) => update("sort", event.target.value)}><option value="newest">Plus récents</option><option value="oldest">Plus anciens</option></select>
        <button className="button" onClick={() => setFilters(initialFilters)}><RotateCcw size={14} />Réinitialiser</button>
      </div>
      {query.isError ? <div className="error-panel">Impossible de charger les incidents.</div> : query.data ? <IncidentTable incidents={query.data.items} /> : <div className="empty-state">Chargement…</div>}
      <div className="pagination"><span>Page {filters.page ?? 1} sur {totalPages}</span><div className="pagination-actions"><button className="button icon-button" aria-label="Page précédente" disabled={(filters.page ?? 1) <= 1} onClick={() => setFilters((current) => ({ ...current, page: (current.page ?? 1) - 1 }))}><ChevronLeft size={16} /></button><button className="button icon-button" aria-label="Page suivante" disabled={(filters.page ?? 1) >= totalPages} onClick={() => setFilters((current) => ({ ...current, page: (current.page ?? 1) + 1 }))}><ChevronRight size={16} /></button></div></div>
    </section>
  </>;
}
