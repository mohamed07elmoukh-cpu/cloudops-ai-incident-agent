"use client";

import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, Calculator, Check, Play, RotateCcw, ShieldCheck, TerminalSquare, X } from "lucide-react";
import { useState } from "react";

import { estimateRemediationCost, remediateIncident, rollbackRemediation, verifyIncident } from "@/lib/api";
import type { Incident, RemediationRequest } from "@/lib/types";

type FieldDefinition = {
  name: string;
  label: string;
  kind: "string" | "integer" | "boolean";
  defaultValue: (incident: Incident) => string;
};

type RemediationDefinition = {
  runbook: string;
  description: string;
  verificationMetric: string;
  verificationDefault: string;
  approvalRequired: boolean;
  fields: FieldDefinition[];
};

const definitions: Record<string, RemediationDefinition> = {
  EC2_CAPACITY_SATURATION: {
    runbook: "scale_ec2_auto_scaling_group",
    description: "Augmente le nombre d’instances de l’Auto Scaling Group.",
    verificationMetric: "CPUUtilization",
    verificationDefault: "55",
    approvalRequired: false,
    fields: [
      { name: "auto_scaling_group_name", label: "Auto Scaling Group", kind: "string", defaultValue: (incident) => incident.source },
      { name: "desired_capacity", label: "Capacité désirée", kind: "integer", defaultValue: () => "2" },
    ],
  },
  DYNAMODB_CAPACITY_SATURATION: {
    runbook: "scale_dynamodb_capacity",
    description: "Augmente les capacités provisionnées de lecture et d’écriture.",
    verificationMetric: "ThrottledRequests",
    verificationDefault: "0",
    approvalRequired: false,
    fields: [
      { name: "table_name", label: "Table DynamoDB", kind: "string", defaultValue: (incident) => incident.source },
      { name: "read_capacity_units", label: "RCU cible", kind: "integer", defaultValue: () => "100" },
      { name: "write_capacity_units", label: "WCU cible", kind: "integer", defaultValue: () => "50" },
    ],
  },
  RDS_STORAGE_LOW: {
    runbook: "scale_rds_storage",
    description: "Augmente la limite d’auto-scaling du stockage RDS.",
    verificationMetric: "FreeStorageSpace",
    verificationDefault: "2147483648",
    approvalRequired: false,
    fields: [
      { name: "db_instance_identifier", label: "Instance RDS", kind: "string", defaultValue: (incident) => incident.source },
      { name: "max_allocated_storage_gib", label: "Stockage maximal (GiB)", kind: "integer", defaultValue: () => "500" },
    ],
  },
  RDS_COMPUTE_SATURATION: {
    runbook: "scale_rds_compute",
    description: "Change la classe de l’instance RDS après approbation humaine.",
    verificationMetric: "CPUUtilization",
    verificationDefault: "55",
    approvalRequired: true,
    fields: [
      { name: "db_instance_identifier", label: "Instance RDS", kind: "string", defaultValue: (incident) => incident.source },
      { name: "db_instance_class", label: "Classe cible", kind: "string", defaultValue: () => "db.t3.large" },
      { name: "apply_immediately", label: "Appliquer immédiatement", kind: "boolean", defaultValue: () => "false" },
    ],
  },
};

export function AwsRemediationPanel({
  incident,
  invalidate,
}: {
  incident: Incident;
  invalidate: () => Promise<void>;
}) {
  const definition = definitions[incident.incident_type];
  const [values, setValues] = useState<Record<string, string>>({});
  const [costEstimate, setCostEstimate] = useState("50");
  const [approvedBy, setApprovedBy] = useState("");
  const [verificationValue, setVerificationValue] = useState(
    definition?.verificationDefault ?? "0",
  );
  const [confirmOpen, setConfirmOpen] = useState(false);
  const parameters = () => Object.fromEntries(
    definition.fields.map((field) => {
      const raw = values[field.name] ?? field.defaultValue(incident);
      const value = field.kind === "integer" ? Number(raw) : field.kind === "boolean" ? raw === "true" : raw;
      return [field.name, value];
    }),
  );
  const pricing = useMutation({
    mutationFn: () => estimateRemediationCost(incident.id, {
      runbook_name: definition.runbook,
      parameters: parameters(),
    }),
    onSuccess: (estimate) => setCostEstimate(String(estimate.monthly_delta_usd)),
  });
  const remediation = useMutation({
    mutationFn: () => {
      if (!definition) throw new Error("Aucun runbook AWS pour ce type d’incident");
      const request: RemediationRequest = {
        runbook_name: definition.runbook,
        parameters: parameters(),
        estimated_monthly_cost_delta_usd: Number(costEstimate),
      };
      if (approvedBy) request.approved_by = approvedBy;
      return remediateIncident(incident.id, request);
    },
    onSuccess: async () => {
      setConfirmOpen(false);
      await invalidate();
    },
  });
  const verification = useMutation({
    mutationFn: () => verifyIncident(
      incident.id,
      Number(verificationValue),
      definition?.verificationMetric ?? "cpu_usage_percent",
    ),
    onSuccess: invalidate,
  });
  const rollback = useMutation({
    mutationFn: (executionId: string) => rollbackRemediation(
      incident.id,
      executionId,
      approvedBy || undefined,
    ),
    onSuccess: invalidate,
  });

  if (!definition) return null;
  const canRemediate = incident.status === "OPEN" || incident.status === "INVESTIGATING";
  const canVerify = incident.status === "VERIFYING";

  return <>
    <section className="card">
      <div className="card-header"><h2>Remédiation AWS</h2><ShieldCheck size={17} className="subtle" /></div>
      <div className="card-body">
        <div className="runbook">
          <div className="runbook-name"><TerminalSquare size={16} />{definition.runbook} <span className="mono">v1.0</span></div>
          <p>{definition.description} Le serveur décide entre simulation et exécution AWS réelle.</p>
        </div>
        <div className="action-stack">
          {definition.fields.map((field) => field.kind === "boolean" ? (
            <label className="field" key={field.name}>{field.label}<select className="select" value={values[field.name] ?? field.defaultValue(incident)} onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.target.value }))}><option value="false">Non, fenêtre de maintenance</option><option value="true">Oui</option></select></label>
          ) : (
            <label className="field" key={field.name}>{field.label}<input className="input" type={field.kind === "integer" ? "number" : "text"} value={values[field.name] ?? field.defaultValue(incident)} onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.target.value }))} /></label>
          ))}
          <label className="field">Coût mensuel supplémentaire estimé (USD)<input className="input" type="number" min="0" value={costEstimate} onChange={(event) => setCostEstimate(event.target.value)} /></label>
          <button className="button" type="button" disabled={pricing.isPending} onClick={() => pricing.mutate()}><Calculator size={14} />{pricing.isPending ? "Calcul en cours…" : "Estimer le coût"}</button>
          {pricing.data && <div className="notice"><strong>+{pricing.data.monthly_delta_usd.toFixed(2)} {pricing.data.currency}/mois</strong> · {pricing.data.source}<br />{pricing.data.assumptions.join(" · ")}</div>}
          {definition.approvalRequired && <label className="field">Approbateur<input className="input" type="email" placeholder="operator@example.com" value={approvedBy} onChange={(event) => setApprovedBy(event.target.value)} /></label>}
          <button className="button primary" disabled={!canRemediate || remediation.isPending || (definition.approvalRequired && !approvedBy)} onClick={() => setConfirmOpen(true)}><Play size={14} />{remediation.isPending ? "Exécution…" : "Lancer le runbook"}</button>
          {canVerify && <form className="verify-form" onSubmit={(event) => { event.preventDefault(); verification.mutate(); }}><input className="input" aria-label={`Valeur ${definition.verificationMetric} de vérification`} type="number" value={verificationValue} onChange={(event) => setVerificationValue(event.target.value)} /><button className="button" disabled={verification.isPending}><Check size={14} />Vérifier</button></form>}
          {(pricing.error || remediation.error || verification.error || rollback.error) && <div className="notice error">{(pricing.error ?? remediation.error ?? verification.error ?? rollback.error)?.message}</div>}
        </div>
      </div>
    </section>
    {incident.remediation_executions.some((execution) => ["VERIFYING", "SUCCEEDED"].includes(execution.status)) && <section className="card"><div className="card-header"><h2>Rollback</h2><RotateCcw size={16} className="subtle" /></div><div className="card-body action-stack">{incident.remediation_executions.filter((execution) => ["VERIFYING", "SUCCEEDED"].includes(execution.status)).map((execution) => <button className="button" key={execution.id} disabled={rollback.isPending || (definition.approvalRequired && !approvedBy)} onClick={() => rollback.mutate(execution.id)}><RotateCcw size={14} />Restaurer l’état avant {execution.runbook_name}</button>)}</div></section>}
    {confirmOpen && <div className="modal-backdrop" role="presentation" onMouseDown={() => setConfirmOpen(false)}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="aws-confirm-title" onMouseDown={(event) => event.stopPropagation()}><div className="modal-icon"><AlertTriangle size={20} /></div><h2 id="aws-confirm-title">Confirmer la mise à l’échelle</h2><p>Le runbook <strong>{definition.runbook}</strong> sera exécuté avec un plafond de coût estimé à <strong>{costEstimate} USD/mois</strong>.</p><div className="modal-actions"><button className="button" onClick={() => setConfirmOpen(false)}><X size={14} />Annuler</button><button className="button primary" onClick={() => remediation.mutate()} disabled={remediation.isPending}><Play size={14} />Confirmer</button></div></section></div>}
  </>;
}
