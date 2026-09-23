import { useCallback, useEffect, useMemo, useState } from "react";
import { Icon } from "../components/icon";
import { EmptyState, ErrorNotice, LoadingPanel, Panel } from "../components/panel";
import { StatusBadge } from "../components/status-badge";
import { useDocumentTitle } from "../hooks/use-document-title";
import { cloudWardApi } from "../lib/api";
import { humanize, normalizedCheck } from "../lib/format";
import type { HealthResponse, Incident, Tone } from "../types";

const telemetrySources = [
  { name: "Prometheus", type: "Metrics", purpose: "Threshold alerts and workload measurements" },
  { name: "Loki", type: "Logs", purpose: "Structured application and platform logs" },
  { name: "Tempo", type: "Traces", purpose: "Distributed trace and span correlation" },
  { name: "Alertmanager", type: "Events", purpose: "Authenticated alert delivery into CloudWard" },
  { name: "OpenTelemetry", type: "Pipeline", purpose: "Metrics, log, and trace collection" },
] as const;

export function ObservabilityPage() {
  useDocumentTitle("Observability");
  const [health, setHealth] = useState<HealthResponse>();
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => { setLoading(true); setError(undefined); setRefreshKey((value) => value + 1); }, []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.allSettled([cloudWardApi.health(controller.signal), cloudWardApi.incidents(controller.signal)])
      .then(([healthData, incidentData]) => {
        if (controller.signal.aborted) return;
        const failures: string[] = [];
        if (healthData.status === "fulfilled") setHealth(healthData.value); else failures.push("readiness checks");
        if (incidentData.status === "fulfilled") setIncidents(incidentData.value); else failures.push("incident evidence");
        setError(failures.length ? `Unavailable: ${failures.join(", ")}` : undefined);
        setLoading(false);
      });
    return () => controller.abort();
  }, [refreshKey]);

  const dependencies = useMemo(() => Object.entries(health?.dependencies ?? health?.checks ?? {}), [health]);
  const evidenceCount = incidents.reduce((total, incident) => total + (incident.evidence?.length ?? incident.evidence_snapshots?.length ?? 0), 0);
  const apiStatus = normalizedCheck(health?.status ?? health?.healthy);

  return (
    <main className="page observability-page">
      <header className="page-header">
        <div><p className="eyebrow">Telemetry and evidence</p><h1>Observability</h1><p>How metrics, logs, traces, and alerts become bounded evidence for CloudWard decisions.</p></div>
        <div className="page-header__actions">
          <a href="http://127.0.0.1:3001" target="_blank" rel="noreferrer" className="button button--primary">Open Grafana ↗</a>
          <button type="button" className="button button--secondary" onClick={refresh} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button>
        </div>
      </header>

      <section className="summary-grid" aria-label="Observability summary">
        <Summary label="API readiness" value={apiStatus.label} tone={apiStatus.tone} />
        <Summary label="Dependency checks" value={health ? String(dependencies.length) : "Unavailable"} />
        <Summary label="Incident evidence" value={String(evidenceCount)} detail="Records in the loaded window" />
        <Summary label="Telemetry sources" value={String(telemetrySources.length)} detail="Configured architecture" />
      </section>

      {error ? <ErrorNotice title="Observability evidence is incomplete" message={error} retry={refresh} /> : null}

      <Panel eyebrow="Evidence pipeline" title="From signal to verified outcome" description="Telemetry informs decisions; it never grants execution authority." className="telemetry-flow-panel">
        <ol className="telemetry-flow" aria-label="Telemetry evidence flow">
          {[
            ["Signal", "Metrics · logs · traces"],
            ["Correlate", "Incident evidence"],
            ["Decide", "Runbook · risk · OPA"],
            ["Act", "Typed allowlisted action"],
            ["Verify", "Before and after evidence"],
          ].map(([title, detail], index) => <li key={title}><span>{index + 1}</span><div><strong>{title}</strong><small>{detail}</small></div><Icon name="arrow" /></li>)}
        </ol>
      </Panel>

      <div className="observability-grid">
        <section className="telemetry-catalog" aria-labelledby="telemetry-catalog-title">
          <header><div><p className="section-index">Configured architecture</p><h2 id="telemetry-catalog-title">Telemetry sources</h2></div><p>Health is not claimed where no API evidence exists.</p></header>
          <div className="telemetry-source-list">
            {telemetrySources.map((source) => <article key={source.name}>
              <span className="telemetry-source__icon"><Icon name="observability" /></span>
              <div><strong>{source.name}</strong><small>{source.type} · {source.purpose}</small></div>
              <StatusBadge label="Not queried" tone="neutral" />
            </article>)}
          </div>
        </section>

        <section className="dependency-panel" aria-labelledby="readiness-title">
          <header><div><p className="section-index">Live evidence</p><h2 id="readiness-title">Readiness dependencies</h2></div><StatusBadge label={apiStatus.label} tone={apiStatus.tone} dot /></header>
          {loading && !health ? <LoadingPanel label="Loading readiness evidence" /> : dependencies.length ? <div className="health-list">
            {dependencies.map(([name, value]) => {
              const status = normalizedCheck(value);
              return <article className={`health-row health-row--${status.tone}`} key={name}><span className={`health-dot health-dot--${status.tone}`} /><div><h3>{humanize(name)}</h3><p>{status.detail ?? "Readiness check"}</p></div><strong>{status.label}</strong></article>;
            })}
          </div> : <EmptyState title="No readiness checks returned" detail="Dependency health remains unavailable until the API supplies evidence." />}
        </section>
      </div>
    </main>
  );
}

function Summary({ label, value, detail, tone = "neutral" }: { label: string; value: string; detail?: string; tone?: Tone }) {
  return <article className="summary-card" data-tone={tone}><span>{label}</span><strong className="summary-card__compact">{value}</strong>{detail ? <small>{detail}</small> : null}</article>;
}
