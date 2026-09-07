"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  CloudCog,
  Database,
  RotateCcw,
  Server,
  TableProperties,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getLiveMetrics } from "@/lib/api";
import type {
  CloudResourceType,
  LiveMetricMarker,
  LiveMetricSeries,
  LiveResourceMetrics,
} from "@/lib/types";

const WINDOWS = [15, 60, 180] as const;
const MARKER_COLORS = {
  detection: "#d93025",
  remediation: "#0b57d0",
  rollback: "#b06000",
};

const SERIES_AXES: Record<string, "primary" | "secondary"> = {
  in_service: "secondary",
  desired: "secondary",
  throttles: "secondary",
  free_storage_gib: "secondary",
  connections: "secondary",
};

function ResourceIcon({ resourceType }: { resourceType: CloudResourceType }) {
  if (resourceType === "EC2") return <Server size={18} />;
  if (resourceType === "DYNAMODB") return <TableProperties size={18} />;
  return <Database size={18} />;
}

function formatMetric(value: number | undefined, unit: string, compact = false): string {
  if (value === undefined || Number.isNaN(value)) return "—";
  const digits = compact || Number.isInteger(value) ? 0 : 1;
  const formatted = new Intl.NumberFormat("fr-FR", {
    maximumFractionDigits: digits,
    notation: value >= 10_000 ? "compact" : "standard",
  }).format(value);
  return unit === "%" ? `${formatted} %` : `${formatted} ${unit}`;
}

function timeLabel(value: number): string {
  return new Intl.DateTimeFormat("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function summaryFor(resource: LiveResourceMetrics) {
  const latest = resource.points.at(-1)?.values ?? {};
  if (resource.resource_type === "EC2") {
    return [
      { label: "CPU moyen", value: formatMetric(latest.cpu, "%") },
      { label: "Instances actives", value: formatMetric(latest.in_service, "", true) },
      { label: "Capacité désirée", value: formatMetric(latest.desired, "", true) },
    ];
  }
  if (resource.resource_type === "DYNAMODB") {
    return [
      {
        label: "Lecture",
        value: `${formatMetric(latest.consumed_read, "", true)} / ${formatMetric(latest.provisioned_read, " RCU", true)}`,
      },
      {
        label: "Écriture",
        value: `${formatMetric(latest.consumed_write, "", true)} / ${formatMetric(latest.provisioned_write, " WCU", true)}`,
      },
      { label: "Throttling", value: formatMetric(latest.throttles, "req.", true) },
    ];
  }
  return [
    { label: "CPU moyen", value: formatMetric(latest.cpu, "%") },
    { label: "Stockage libre", value: formatMetric(latest.free_storage_gib, "GiB") },
    { label: "Connexions", value: formatMetric(latest.connections, "", true) },
  ];
}

function MetricLine({ series }: { series: LiveMetricSeries }) {
  const axis = SERIES_AXES[series.key] ?? "primary";
  if (series.key === "cpu") {
    return (
      <Area
        key={series.key}
        yAxisId={axis}
        type="monotone"
        dataKey={series.key}
        name={series.key}
        stroke={series.color}
        strokeWidth={2.3}
        fill={`url(#fill-${series.key})`}
        connectNulls
        isAnimationActive={false}
      />
    );
  }
  if (series.key === "throttles") {
    return (
      <Bar
        key={series.key}
        yAxisId={axis}
        dataKey={series.key}
        name={series.key}
        fill={series.color}
        fillOpacity={0.24}
        radius={[2, 2, 0, 0]}
        isAnimationActive={false}
      />
    );
  }
  const dashed = series.key.includes("provisioned") || series.key === "desired";
  return (
    <Line
      key={series.key}
      yAxisId={axis}
      type={dashed ? "stepAfter" : "monotone"}
      dataKey={series.key}
      name={series.key}
      stroke={series.color}
      strokeWidth={dashed ? 1.7 : 2}
      strokeDasharray={dashed ? "5 4" : undefined}
      dot={false}
      connectNulls
      isAnimationActive={false}
    />
  );
}

function LifecycleMarker({ marker }: { marker: LiveMetricMarker }) {
  return (
    <ReferenceLine
      x={Date.parse(marker.timestamp)}
      stroke={MARKER_COLORS[marker.kind]}
      strokeWidth={1.25}
      strokeDasharray="4 4"
      ifOverflow="extendDomain"
    />
  );
}

function ResourceChart({ resource }: { resource: LiveResourceMetrics }) {
  const points = resource.points.map((point) => ({
    time: Date.parse(point.timestamp),
    ...point.values,
  }));
  const seriesByKey = new Map(resource.series.map((series) => [series.key, series]));
  const summary = summaryFor(resource);
  const hasCpu = resource.series.some((series) => series.key === "cpu");

  return (
    <article className="live-resource-card">
      <header className="live-resource-head">
        <span className={`live-resource-icon ${resource.resource_type.toLowerCase()}`}>
          <ResourceIcon resourceType={resource.resource_type} />
        </span>
        <div className="live-resource-title">
          <div>
            <h3>{resource.title}</h3>
            <span>{resource.subtitle}</span>
          </div>
          <code>{resource.resource_id}</code>
        </div>
        <span className={`resource-health ${resource.status}`}>
          {resource.status === "healthy" ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}
          {resource.status === "healthy" ? "Stable" : "Attention"}
        </span>
      </header>

      <div className="live-summary-grid">
        {summary.map((item) => (
          <div className="live-summary-item" key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>

      {resource.resource_type === "RDS" && (
        <div className="instance-class-row">
          <span>Classe d’instance</span>
          <code>{resource.metadata.instance_class ?? "inconnue"}</code>
        </div>
      )}

      <div className="live-chart">
        {points.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={points} syncId="cloud-capacity" margin={{ top: 12, right: 0, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="fill-cpu" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#0b57d0" stopOpacity={0.2} />
                  <stop offset="100%" stopColor="#0b57d0" stopOpacity={0.01} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke="#edf0f4" strokeDasharray="3 4" />
              <XAxis
                dataKey="time"
                type="number"
                scale="time"
                domain={["dataMin", "dataMax"]}
                axisLine={false}
                tickLine={false}
                minTickGap={42}
                tickFormatter={timeLabel}
                tick={{ fill: "#80868b", fontSize: 9 }}
              />
              <YAxis
                yAxisId="primary"
                domain={hasCpu ? [0, 100] : [0, "auto"]}
                axisLine={false}
                tickLine={false}
                width={38}
                tick={{ fill: "#80868b", fontSize: 9 }}
              />
              <YAxis yAxisId="secondary" orientation="right" hide domain={[0, "auto"]} />
              <Tooltip
                labelFormatter={(label) => timeLabel(Number(label))}
                formatter={(value, name) => {
                  const series = seriesByKey.get(String(name));
                  return [
                    formatMetric(Number(value ?? 0), series?.unit ?? ""),
                    series?.label ?? String(name),
                  ];
                }}
                contentStyle={{
                  border: "1px solid #dfe3eb",
                  borderRadius: 10,
                  boxShadow: "0 10px 28px rgba(32,33,36,.14)",
                  fontSize: 11,
                }}
              />
              {resource.markers.map((marker) => (
                <LifecycleMarker marker={marker} key={`${marker.kind}-${marker.timestamp}`} />
              ))}
              {resource.series.map((series) => (
                <MetricLine series={series} key={series.key} />
              ))}
            </ComposedChart>
          </ResponsiveContainer>
        ) : (
          <div className="live-empty"><Activity size={19} />En attente de points CloudWatch</div>
        )}
      </div>

      <div className="live-series-legend">
        {resource.series.map((series) => (
          <span key={series.key}><i style={{ background: series.color }} />{series.label}</span>
        ))}
      </div>

      <footer className="event-rail">
        {resource.markers.length ? resource.markers.slice(-3).map((marker) => {
          const content = <><i className={marker.kind} />{marker.label}<time>{timeLabel(Date.parse(marker.timestamp))}</time></>;
          return marker.incident_id ? (
            <Link href={`/incidents/${marker.incident_id}`} key={`${marker.kind}-${marker.timestamp}`}>{content}</Link>
          ) : (
            <span key={`${marker.kind}-${marker.timestamp}`}>{content}</span>
          );
        }) : <span className="no-event"><Zap size={12} />Aucun événement sur cette période</span>}
      </footer>
    </article>
  );
}

export function LiveInfrastructure() {
  const [windowMinutes, setWindowMinutes] = useState<(typeof WINDOWS)[number]>(60);
  const metrics = useQuery({
    queryKey: ["live-metrics", windowMinutes],
    queryFn: () => getLiveMetrics(windowMinutes),
    refetchInterval: 8_000,
    placeholderData: keepPreviousData,
    retry: 1,
  });

  return (
    <section className="live-infrastructure" aria-labelledby="live-infrastructure-title">
      <div className="live-section-head">
        <div className="live-section-title">
          <span className="live-cloud-icon"><CloudCog size={19} /></span>
          <div>
            <span className="section-kicker">TÉLÉMÉTRIE CLOUDWATCH</span>
            <h2 id="live-infrastructure-title">Capacité de l’infrastructure</h2>
            <p>Signaux opérationnels et décisions de remédiation sur une même chronologie.</p>
          </div>
        </div>
        <div className="live-controls">
          <span className={`live-source-pill ${metrics.data?.mode ?? "loading"}`}>
            <span className="live-pulse" />
            {metrics.data?.mode === "aws" ? `AWS · ${metrics.data.region}` : "Scénario démo"}
          </span>
          <div className="window-control" aria-label="Période des graphiques">
            {WINDOWS.map((value) => (
              <button
                className={windowMinutes === value ? "active" : ""}
                key={value}
                onClick={() => setWindowMinutes(value)}
                type="button"
              >
                {value < 60 ? `${value} min` : `${value / 60} h`}
              </button>
            ))}
          </div>
        </div>
      </div>

      {metrics.isError ? (
        <div className="live-metrics-error">
          <AlertTriangle size={18} />
          <div><strong>Métriques indisponibles</strong><span>Vérifiez les identifiants de ressources et la permission cloudwatch:GetMetricData.</span></div>
        </div>
      ) : (
        <div className="live-resource-grid">
          {metrics.data?.resources.map((resource) => (
            <ResourceChart resource={resource} key={resource.resource_type} />
          )) ?? ["EC2", "DYNAMODB", "RDS"].map((resource) => (
            <div className="live-resource-card live-card-skeleton skeleton" key={resource} />
          ))}
        </div>
      )}

      <div className="live-section-footer">
        <span><span className="marker-key detection" />Détection</span>
        <span><span className="marker-key remediation" />Remédiation</span>
        <span><span className="marker-key rollback" />Rollback</span>
        <span className="live-updated">
          <RotateCcw size={11} /> Actualisation automatique · {metrics.data?.refresh_seconds ?? 8} s
        </span>
      </div>
    </section>
  );
}
