"use client";

import { useQuery } from "@tanstack/react-query";
import {
  BriefcaseBusiness,
  Gauge,
  ShieldCheck,
  Target,
  TimerReset,
} from "lucide-react";

import { getBusinessImpact, getIncidentBusinessImpact } from "@/lib/api";
import type { BusinessImpact } from "@/lib/types";

const statusLabels = {
  healthy: "SLO maîtrisé",
  at_risk: "Service à risque",
  exhausted: "Budget épuisé",
};

function formatMinutes(value: number | null): string {
  if (value === null) return "Données insuffisantes";
  if (value < 60) return `${Math.max(0, Math.round(value))} min`;
  if (value < 24 * 60) return `${(value / 60).toFixed(1)} h`;
  return `${(value / (24 * 60)).toFixed(1)} j`;
}

function formatSaturation(value: number | null): string {
  if (value !== null && value <= 0) return "Imminente";
  return formatMinutes(value);
}

function formatPercent(value: number, precision = 2): string {
  return `${value.toLocaleString("fr-FR", {
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  })} %`;
}

function BusinessImpactCard({ impact }: { impact: BusinessImpact }) {
  const forecastSource =
    impact.saturation_method === "observed_trend"
      ? "Tendance métrique observée"
      : impact.saturation_method === "conservative_projection"
        ? "Projection conservatrice"
        : "Prévision indisponible";
  return (
    <section className={`card business-impact-card ${impact.status}`}>
      <div className="business-impact-head">
        <div className="business-service-identity">
          <span className="business-service-icon"><BriefcaseBusiness size={20} /></span>
          <div>
            <span className="section-kicker">IMPACT MÉTIER &amp; SLO</span>
            <h2>{impact.service_name}</h2>
            <span>{impact.criticality === "critical" ? "Service critique" : "Service prioritaire"} · fenêtre de {impact.slo_window_days} jours</span>
          </div>
        </div>
        <span className={`slo-status ${impact.status}`}>{statusLabels[impact.status]}</span>
      </div>

      <div className="business-impact-statement">
        <strong>{impact.summary}</strong>
        <span>{impact.active_incidents} incident(s) actif(s) · {impact.affected_resources.length ? impact.affected_resources.join(" · ") : "aucune ressource menacée"}</span>
      </div>

      <div className="slo-metric-grid">
        <article>
          <span className="slo-metric-icon risk"><BriefcaseBusiness size={16} /></span>
          <div><span>Trafic menacé</span><strong>{impact.transactions_at_risk_per_minute.toFixed(0)} <small>txn/min</small></strong></div>
        </article>
        <article>
          <span className="slo-metric-icon"><Target size={16} /></span>
          <div><span>Disponibilité / objectif</span><strong>{formatPercent(impact.availability_percent, 3)} <small>/ {formatPercent(impact.slo_target_percent, 1)}</small></strong></div>
        </article>
        <article>
          <span className="slo-metric-icon"><ShieldCheck size={16} /></span>
          <div><span>Budget restant</span><strong>{formatMinutes(impact.error_budget_remaining_minutes)}</strong></div>
        </article>
        <article>
          <span className="slo-metric-icon warning"><TimerReset size={16} /></span>
          <div><span>Avant saturation</span><strong>{formatSaturation(impact.time_to_saturation_minutes)}</strong></div>
        </article>
      </div>

      <div className="error-budget-panel">
        <div className="error-budget-copy">
          <div>
            <span>Budget d’erreur SLO</span>
            <strong>{formatPercent(impact.error_budget_remaining_percent)} restant</strong>
          </div>
          <span>{impact.error_budget_consumed_minutes.toFixed(1)} min consommées sur {impact.error_budget_total_minutes.toFixed(1)} min · burn rate ×{impact.error_budget_burn_rate.toFixed(2)}</span>
        </div>
        <div
          className="error-budget-track"
          role="progressbar"
          aria-label="Budget d’erreur restant"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={impact.error_budget_remaining_percent}
        >
          <span style={{ width: `${impact.error_budget_remaining_percent}%` }} />
        </div>
        <div className="saturation-source"><Gauge size={13} /><span>{forecastSource}{impact.saturation_metric ? ` · ${impact.saturation_metric}` : ""}</span></div>
      </div>
    </section>
  );
}

export function DashboardBusinessImpact() {
  const query = useQuery({
    queryKey: ["business-impact"],
    queryFn: getBusinessImpact,
    refetchInterval: 10_000,
  });
  if (query.isError) return <div className="error-panel">L’impact métier et le SLO sont momentanément indisponibles.</div>;
  if (!query.data) return <div className="card business-impact-skeleton skeleton" />;
  const priority = query.data.services[0];
  return priority ? <BusinessImpactCard impact={priority} /> : null;
}

export function IncidentBusinessImpact({ incidentId }: { incidentId: string }) {
  const query = useQuery({
    queryKey: ["incident-business-impact", incidentId],
    queryFn: () => getIncidentBusinessImpact(incidentId),
    refetchInterval: 10_000,
  });
  if (query.isError) return <div className="error-panel">Impossible de calculer l’impact métier de cet incident.</div>;
  if (!query.data) return <div className="card business-impact-skeleton skeleton" />;
  return <BusinessImpactCard impact={query.data} />;
}
