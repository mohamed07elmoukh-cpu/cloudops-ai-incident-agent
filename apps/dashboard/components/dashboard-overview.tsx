"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  Clock3,
  Database,
  RefreshCw,
  Server,
  ShieldCheck,
  TableProperties,
} from "lucide-react";
import Link from "next/link";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { IncidentTable } from "@/components/incident-table";
import { LiveInfrastructure } from "@/components/live-infrastructure";
import { formatDuration, getIncidents, getStatistics, getSystemHealth } from "@/lib/api";
import type { Incident, Statistics } from "@/lib/types";

function MetricCard({
  label,
  value,
  note,
  tone,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  note: string;
  tone?: string;
  icon: typeof Activity;
}) {
  return (
    <article className={`metric-card ${tone ?? ""}`}>
      <div className="metric-top">
        <span className="metric-icon"><Icon size={17} /></span>
        <span className="metric-note">{note}</span>
      </div>
      <div className="metric-value">{value}</div>
      <div className="metric-label">{label}</div>
    </article>
  );
}

function IncidentTrend({ statistics }: { statistics: Statistics }) {
  const data = statistics.daily_trend.map((point) => ({
    ...point,
    label: new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "short" }).format(
      new Date(`${point.date}T12:00:00`),
    ),
  }));
  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 16, right: 16, left: -24, bottom: 0 }}>
          <defs>
            <linearGradient id="detectedFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#0b57d0" stopOpacity={0.16} />
              <stop offset="100%" stopColor="#0b57d0" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="#e7e8eb" strokeDasharray="3 3" />
          <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fill: "#747775", fontSize: 10 }} />
          <YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={{ fill: "#747775", fontSize: 10 }} />
          <Tooltip contentStyle={{ border: "1px solid #dfe1e5", borderRadius: 10, boxShadow: "0 8px 24px rgba(60,64,67,.14)", fontSize: 12 }} />
          <Area type="monotone" dataKey="detected" name="Détectés" stroke="#0b57d0" strokeWidth={2.2} fill="url(#detectedFill)" />
          <Area type="monotone" dataKey="resolved" name="Résolus" stroke="#188038" strokeWidth={2.2} fill="transparent" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function diagnosisFor(incident: Incident | undefined): { cause: string; action: string; confidence: number } {
  if (!incident) return { cause: "Aucun signal anormal corrélé pour le moment.", action: "Continuer la surveillance", confidence: 100 };
  const diagnoses: Record<string, { cause: string; action: string }> = {
    CPU_SATURATION: { cause: "La charge CPU dépasse le seuil opérationnel du service.", action: "Augmenter la capacité du service" },
    EC2_CAPACITY_SATURATION: { cause: "Le groupe EC2 ne dispose plus de marge pour absorber la charge.", action: "Augmenter la capacité désirée" },
    DYNAMODB_CAPACITY_SATURATION: { cause: "Le débit provisionné ne couvre plus le volume de requêtes.", action: "Ajuster les RCU et WCU" },
    RDS_STORAGE_LOW: { cause: "L’espace libre RDS se rapproche du seuil critique.", action: "Relever la limite de stockage" },
    RDS_COMPUTE_SATURATION: { cause: "La classe RDS actuelle est sous-dimensionnée pour la charge.", action: "Faire approuver une classe supérieure" },
  };
  const match = diagnoses[incident.incident_type] ?? {
    cause: "Les signaux corrélés indiquent une dégradation de capacité.",
    action: "Examiner l’incident",
  };
  return { ...match, confidence: incident.severity === "CRITICAL" ? 96 : 91 };
}

function ResourceCapability({
  icon: Icon,
  name,
  description,
  detail,
}: {
  icon: typeof Server;
  name: string;
  description: string;
  detail: string;
}) {
  return (
    <article className="resource-capability">
      <span className="resource-icon"><Icon size={18} /></span>
      <div><strong>{name}</strong><p>{description}</p></div>
      <span className="resource-state"><span className="status-dot" />{detail}</span>
    </article>
  );
}

export function DashboardOverview() {
  const statistics = useQuery({ queryKey: ["statistics"], queryFn: getStatistics, refetchInterval: 5_000 });
  const incidents = useQuery({ queryKey: ["incidents", "recent"], queryFn: () => getIncidents({ page_size: 5 }), refetchInterval: 5_000 });
  const health = useQuery({ queryKey: ["system-health"], queryFn: getSystemHealth, refetchInterval: 5_000, retry: false });
  const refresh = () => { void statistics.refetch(); void incidents.refetch(); void health.refetch(); };
  if (statistics.isError || incidents.isError) return <div className="error-panel">Impossible de joindre l’API CloudOps. Vérifiez que la stack est démarrée.</div>;

  const stats = statistics.data;
  const activeIncident = incidents.data?.items.find((incident) => !["RESOLVED", "FAILED"].includes(incident.status));
  const diagnosis = diagnosisFor(activeIncident);
  const healthyComponents = Object.values(health.data?.components ?? {}).filter((item) => item.status === "healthy").length;

  return <>
    <div className="page-heading dashboard-heading">
      <div>
        <span className="eyebrow">VUE OPÉRATIONNELLE · PRODUCTION</span>
        <h1>Centre de contrôle</h1>
        <p>Une vue claire des incidents, de leur diagnostic et des décisions de remédiation.</p>
      </div>
      <div className="page-actions">
        <span className="last-updated"><span className="status-dot" />Données en direct · 5 s</span>
        <button className="button" onClick={refresh} aria-label="Actualiser"><RefreshCw size={15} />Actualiser</button>
      </div>
    </div>

    <section className={`command-banner ${(stats?.active ?? 0) > 0 ? "attention" : "healthy"}`}>
      <div className="command-banner-icon">{(stats?.active ?? 0) > 0 ? <AlertTriangle size={22} /> : <CheckCircle2 size={22} />}</div>
      <div className="command-banner-copy">
        <span>État de l’environnement</span>
        <h2>{(stats?.active ?? 0) > 0 ? `${stats?.active} incident${stats?.active === 1 ? "" : "s"} nécessite${stats?.active === 1 ? "" : "nt"} votre attention` : "Aucun incident actif"}</h2>
        <p>{(stats?.active ?? 0) > 0 ? "Le diagnostic automatique a identifié une action de capacité à examiner." : "Tous les services surveillés fonctionnent dans leurs seuils attendus."}</p>
      </div>
      <Link href={activeIncident ? `/incidents/${activeIncident.id}` : "/incidents"} className="button banner-action">
        {(stats?.active ?? 0) > 0 ? "Examiner l’incident" : "Voir l’historique"}<ArrowRight size={15} />
      </Link>
    </section>

    <section className="metric-grid" aria-label="Indicateurs principaux">
      <MetricCard label="Incidents actifs" value={stats?.active ?? "—"} note="Maintenant" tone="danger" icon={AlertTriangle} />
      <MetricCard label="Taux de résolution" value={stats?.total ? `${Math.round(((stats.resolved ?? 0) / stats.total) * 100)} %` : "—"} note={`${stats?.resolved ?? 0} résolus`} tone="success" icon={CheckCircle2} />
      <MetricCard label="Temps moyen de résolution" value={formatDuration(stats?.average_resolution_seconds ?? null)} note="MTTR" icon={Clock3} />
      <MetricCard label="État de la plateforme" value={health.data?.status === "healthy" ? "Opérationnel" : health.isLoading ? "—" : "Dégradé"} note={`${healthyComponents}/4 services`} tone={health.data?.status === "healthy" ? "success" : "warning"} icon={Activity} />
    </section>

    <LiveInfrastructure />

    <section className="dashboard-grid insight-grid">
      <article className="card trend-card">
        <div className="card-header">
          <div><span className="section-kicker">ACTIVITÉ</span><h2>Incidents détectés et résolus</h2><span className="subtle">Évolution sur les 14 derniers jours</span></div>
          <span className="chart-legend"><i className="detected" />Détectés <i className="resolved" />Résolus</span>
        </div>
        {stats ? <IncidentTrend statistics={stats} /> : <div className="chart-wrap skeleton" />}
      </article>

      <article className="card ai-brief-card">
        <div className="ai-brief-header">
          <span className="ai-symbol"><Bot size={19} /></span>
          <div><span className="section-kicker">DIAGNOSTIC AUTOMATIQUE</span><h2>Analyse prioritaire</h2></div>
          <span className="confidence">{diagnosis.confidence}% fiable</span>
        </div>
        <div className="ai-brief-body">
          <span className="ai-label">Cause probable</span>
          <p className="ai-cause">{diagnosis.cause}</p>
          {activeIncident && <div className="signal-source"><span className={`severity-marker ${activeIncident.severity.toLowerCase()}`} /> <span>{activeIncident.source}</span><small>{activeIncident.incident_type}</small></div>}
          <div className="recommendation"><ShieldCheck size={16} /><div><span>Action recommandée</span><strong>{diagnosis.action}</strong></div></div>
        </div>
        <Link href={activeIncident ? `/incidents/${activeIncident.id}` : "/incidents"} className="ai-brief-footer">Voir les preuves et décider <ArrowRight size={15} /></Link>
      </article>
    </section>

    <section className="card resources-card">
      <div className="card-header">
        <div><span className="section-kicker">CAPACITÉ CLOUD</span><h2>Remédiations disponibles</h2><span className="subtle">Actions contrôlées par politiques, coût et approbation</span></div>
        <Link href="/system" className="text-link">État du système <ArrowRight size={14} /></Link>
      </div>
      <div className="resource-grid">
        <ResourceCapability icon={Server} name="Amazon EC2" description="Auto Scaling Group" detail="Scale-out prêt" />
        <ResourceCapability icon={TableProperties} name="DynamoDB" description="Capacité RCU / WCU" detail="Provisionné" />
        <ResourceCapability icon={Database} name="Amazon RDS" description="Compute et stockage" detail="Approbation active" />
      </div>
    </section>

    <section className="card table-shell recent-incidents">
      <div className="card-header">
        <div><span className="section-kicker">FILE OPÉRATIONNELLE</span><h2>Incidents récents</h2><span className="subtle">Classés du signal le plus récent au plus ancien</span></div>
        <Link href="/incidents" className="button">Tous les incidents <ArrowRight size={14} /></Link>
      </div>
      {incidents.data ? <IncidentTable incidents={incidents.data.items} /> : <div className="empty-state">Chargement des incidents…</div>}
    </section>
  </>;
}
