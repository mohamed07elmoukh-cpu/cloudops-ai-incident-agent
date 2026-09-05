"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Database, HardDrive, RefreshCw, Server, Workflow } from "lucide-react";

import { formatDate, getSystemHealth } from "@/lib/api";

const icons = { api: Server, postgresql: Database, sqs: HardDrive, worker: Workflow };
const labels = { api: "API CloudOps", postgresql: "PostgreSQL", sqs: "File SQS", worker: "Incident Worker" };

export function SystemOverview() {
  const health = useQuery({ queryKey: ["system-health"], queryFn: getSystemHealth, refetchInterval: 5_000, retry: false });
  return <>
    <div className="page-heading"><div><span className="eyebrow">Infrastructure locale</span><h1>État du système</h1><p>Disponibilité des composants essentiels de la chaîne événementielle.</p></div><button className="button" onClick={() => void health.refetch()}><RefreshCw size={14} />Actualiser</button></div>
    {health.isError ? <div className="error-panel">L’API de santé est indisponible. Vérifiez les conteneurs Docker.</div> : <>
      <section className="card health-summary"><span className="health-icon"><CheckCircle2 size={21} /></span><div><h2>{health.data?.status === "healthy" ? "Tous les systèmes sont opérationnels" : "Vérification en cours"}</h2><p>Dernière vérification : {formatDate(health.data?.checked_at ?? null)}</p></div></section>
      <section className="health-grid">{Object.entries(health.data?.components ?? {}).map(([name, component]) => { const Icon = icons[name as keyof typeof icons] ?? Server; return <article className="card health-card" key={name}><div className="health-card-head"><span className="health-card-icon"><Icon size={17} /></span><span className={`badge ${component.status === "healthy" ? "resolved" : "failed"}`}>{component.status === "healthy" ? "Disponible" : "Indisponible"}</span></div><h3>{labels[name as keyof typeof labels] ?? name}</h3><p>{component.detail ?? (name === "sqs" ? `${component.visible_messages ?? 0} message(s) visible · ${component.in_flight_messages ?? 0} en vol` : "Connexion vérifiée avec succès.")}</p><footer>Polling automatique · 5 secondes</footer></article>; })}</section>
    </>}
  </>;
}
