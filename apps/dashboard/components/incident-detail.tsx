"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, AlertTriangle, ArrowLeft, Braces, Check, CircleDot, FileClock, Gauge, Play, RefreshCw, ShieldCheck, TerminalSquare, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AwsRemediationPanel } from "@/components/aws-remediation-panel";
import { SeverityBadge, StatusBadge } from "@/components/badges";
import { formatDate, getIncident, getIncidentEvents, getIncidentTimeline, remediateIncident, verifyIncident } from "@/lib/api";
import type { TimelineEntry } from "@/lib/types";

function TimelineIcon({ kind }: { kind: TimelineEntry["kind"] }) {
  const Icon = kind === "evidence" ? Gauge : kind === "event" ? Braces : kind === "remediation" ? TerminalSquare : CircleDot;
  return <span className="timeline-icon"><Icon size={13} /></span>;
}

export function IncidentDetail({ id }: { id: string }) {
  const client = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [cpuValue, setCpuValue] = useState("55");
  const incident = useQuery({ queryKey: ["incident", id], queryFn: () => getIncident(id), refetchInterval: 5_000 });
  const events = useQuery({ queryKey: ["incident-events", id], queryFn: () => getIncidentEvents(id), refetchInterval: 5_000 });
  const timeline = useQuery({ queryKey: ["incident-timeline", id], queryFn: () => getIncidentTimeline(id), refetchInterval: 5_000 });
  const invalidate = async () => { await Promise.all([client.invalidateQueries({ queryKey: ["incident", id] }), client.invalidateQueries({ queryKey: ["incident-timeline", id] }), client.invalidateQueries({ queryKey: ["statistics"] }), client.invalidateQueries({ queryKey: ["incidents"] })]); };
  const remediation = useMutation({ mutationFn: () => remediateIncident(id), onSuccess: async () => { setConfirmOpen(false); await invalidate(); } });
  const verification = useMutation({ mutationFn: () => verifyIncident(id, Number(cpuValue)), onSuccess: invalidate });
  if (incident.isLoading) return <div className="card empty-state">Chargement de l’incident…</div>;
  if (incident.isError || !incident.data) return <div className="error-panel">Incident introuvable ou API indisponible.</div>;
  const item = incident.data;
  const canRemediate = item.status === "OPEN" || item.status === "INVESTIGATING";
  const canVerify = item.status === "VERIFYING";

  return <>
    <div className="page-heading"><div><Link href="/incidents" className="text-link"><ArrowLeft size={14} /> Retour aux incidents</Link><h1 style={{ marginTop: 12 }}>{item.title}</h1><p className="mono">INC-{item.id.slice(0, 8).toUpperCase()} · {item.source}</p></div><div className="page-actions"><SeverityBadge severity={item.severity} /><StatusBadge status={item.status} /></div></div>
    <div className="detail-grid">
      <div className="detail-main">
        <section className="card"><div className="card-header"><h2>Informations générales</h2><Activity size={17} className="subtle" /></div><div className="card-body"><p style={{ marginTop: 0, lineHeight: 1.65, color: "#475467" }}>{item.description}</p><dl className="definition-grid"><div className="definition-item"><dt>Type</dt><dd>{item.incident_type}</dd></div><div className="definition-item"><dt>Détecté le</dt><dd>{formatDate(item.detected_at)}</dd></div><div className="definition-item"><dt>Correlation key</dt><dd className="mono">{item.correlation_key}</dd></div><div className="definition-item"><dt>Résolu le</dt><dd>{formatDate(item.resolved_at)}</dd></div><div className="definition-item"><dt>Tentative de remédiation</dt><dd>{item.remediation_attempted ? "Oui" : "Non"}</dd></div><div className="definition-item"><dt>Échecs de vérification</dt><dd>{item.verification_failures} / 3</dd></div></dl></div></section>
        <section className="card"><div className="card-header"><div><h2>Chronologie</h2><span className="subtle">Cycle de vie et signaux associés</span></div><FileClock size={17} className="subtle" /></div><div className="card-body timeline">{timeline.data?.map((entry, index) => <div className="timeline-item" key={`${entry.timestamp}-${index}`}><TimelineIcon kind={entry.kind} /><div className="timeline-content"><div className="timeline-title"><span>{entry.title}</span><time className="timeline-time">{formatDate(entry.timestamp)}</time></div>{entry.status && <div style={{ marginTop: 7 }}><span className="mono muted">{entry.status}</span></div>}<div className="timeline-detail">{Object.entries(entry.detail).map(([key, value]) => <span key={key} style={{ marginRight: 12 }}>{key}: <span className="mono">{String(value)}</span></span>)}</div></div></div>) ?? <span className="muted">Chargement…</span>}</div></section>
        <section className="card"><div className="card-header"><div><h2>Événements CloudEvent</h2><span className="subtle">Traçabilité du pipeline événementiel</span></div><Braces size={17} className="subtle" /></div><div className="table-scroll"><table><thead><tr><th>Type</th><th>Event ID</th><th>Trace ID</th><th>Traitement</th></tr></thead><tbody>{events.data?.map((event) => <tr key={event.event_id}><td>{event.event_type}</td><td className="mono">{event.event_id.slice(0, 13)}…</td><td className="mono">{event.trace_id.slice(0, 13)}…</td><td><span className="badge resolved">{event.status}</span></td></tr>)}</tbody></table>{events.data?.length === 0 && <div className="empty-state">Aucun CloudEvent lié à cet incident.</div>}</div></section>
      </div>
      <aside className="detail-side">
        <section className="card"><div className="card-header"><h2>Evidence métrique</h2><Gauge size={17} className="subtle" /></div><div className="card-body">{item.evidence.slice().reverse().map((evidence, index) => <article className="evidence-box" key={`${evidence.timestamp}-${index}`}><div className="metric-top"><span className="mono muted">{evidence.metric_name}</span><time className="timeline-time">{formatDate(evidence.timestamp)}</time></div><div className="evidence-value"><strong>{evidence.metric_value.toFixed(1)}</strong><span>% / seuil {evidence.threshold}%</span></div><div className="threshold-track"><div className="threshold-value" style={{ width: `${Math.min(evidence.metric_value, 100)}%` }} /></div></article>)}</div></section>
        {item.incident_type === "CPU_SATURATION" ? <section className="card"><div className="card-header"><h2>Remédiation</h2><ShieldCheck size={17} className="subtle" /></div><div className="card-body"><div className="runbook"><div className="runbook-name"><TerminalSquare size={16} />scale_service <span className="mono">v1.0</span></div><p>Ajuste de façon simulée la capacité du service. Aucun appel AWS réel n’est exécuté.</p></div><div className="action-stack"><button className="button primary" disabled={!canRemediate || remediation.isPending} onClick={() => setConfirmOpen(true)}><Play size={14} />{remediation.isPending ? "Exécution…" : "Lancer le runbook"}</button>{canVerify && <form className="verify-form" onSubmit={(event) => { event.preventDefault(); verification.mutate(); }}><input className="input" aria-label="Valeur CPU de vérification" type="number" min="0" max="100" value={cpuValue} onChange={(event) => setCpuValue(event.target.value)} /><button className="button" disabled={verification.isPending}><Check size={14} />Vérifier</button></form>}{item.status === "RESOLVED" && <div className="notice"><Check size={13} /> Le service a été vérifié et l’incident est résolu.</div>}{(remediation.error || verification.error) && <div className="notice error">{(remediation.error ?? verification.error)?.message}</div>}</div></div></section> : <AwsRemediationPanel incident={item} invalidate={invalidate} />}
        <section className="card"><div className="card-header"><h2>Exécutions</h2><RefreshCw size={16} className="subtle" /></div><div className="card-body">{item.remediation_executions.length ? item.remediation_executions.slice().reverse().map((execution) => <div className="evidence-box" key={execution.idempotency_key}><div className="metric-top"><strong>{execution.runbook_name}</strong><span className="mono muted">{execution.status}</span></div><p className="timeline-detail">Début : {formatDate(execution.started_at)}</p><p className="mono subtle" style={{ overflowWrap: "anywhere" }}>{execution.idempotency_key}</p></div>) : <div className="empty-state" style={{ padding: 20 }}>Aucune exécution.</div>}</div></section>
      </aside>
    </div>
    {confirmOpen && <div className="modal-backdrop" role="presentation" onMouseDown={() => setConfirmOpen(false)}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title" onMouseDown={(event) => event.stopPropagation()}><div className="modal-icon"><AlertTriangle size={20} /></div><h2 id="confirm-title">Confirmer la remédiation</h2><p>Le runbook <strong>scale_service</strong> sera exécuté sur l’incident <span className="mono">INC-{item.id.slice(0, 8).toUpperCase()}</span>. Cette démonstration utilise uniquement l’exécuteur simulé.</p><div className="modal-actions"><button className="button" onClick={() => setConfirmOpen(false)}><X size={14} />Annuler</button><button className="button primary" onClick={() => remediation.mutate()} disabled={remediation.isPending}><Play size={14} />Confirmer</button></div></section></div>}
  </>;
}
