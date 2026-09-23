import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { EmptyState, ErrorNotice, LoadingPanel } from "../components/panel";
import { StatusBadge } from "../components/status-badge";
import { useControlPlaneEvents } from "../hooks/use-control-plane-events";
import { useDocumentTitle } from "../hooks/use-document-title";
import { cloudWardApi } from "../lib/api";
import { displayValue, formatDate, humanize, stateTone } from "../lib/format";
import type { ApprovalRequest, AuditEvent, GitOpsDrift } from "../types";

function list<T>(value: T[] | { items: T[] }): T[] {
  return Array.isArray(value) ? value : value.items;
}

function deploymentEvent(event: AuditEvent) {
  return /DEPLOY|GITOPS|RELEASE|PROMOTION|IMAGE/.test(String(event.event_type ?? event.action).toUpperCase());
}

export function DeploymentsPage() {
  useDocumentTitle("Deployments");
  const [drift, setDrift] = useState<GitOpsDrift[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [refreshKey, setRefreshKey] = useState(0);

  const refresh = useCallback(() => {
    setLoading(true);
    setError(undefined);
    setRefreshKey((value) => value + 1);
  }, []);

  useControlPlaneEvents(useCallback((event) => {
    const kind = String(event.type ?? event.event_type ?? "").toLowerCase();
    if (kind.includes("deploy") || kind.includes("gitops") || kind.includes("approval")) refresh();
  }, [refresh]));

  useEffect(() => {
    const controller = new AbortController();
    Promise.allSettled([
      cloudWardApi.gitopsDrift("staging", controller.signal),
      cloudWardApi.gitopsDrift("production", controller.signal),
      cloudWardApi.audit(controller.signal),
      cloudWardApi.approvals(controller.signal),
    ]).then(([staging, production, audit, approvalData]) => {
      if (controller.signal.aborted) return;
      const failures: string[] = [];
      setDrift([staging, production].flatMap((result) => result.status === "fulfilled" ? [result.value] : []));
      if (staging.status === "rejected") failures.push("staging GitOps state");
      if (production.status === "rejected") failures.push("production GitOps state");
      if (audit.status === "fulfilled") setEvents(list(audit.value).filter(deploymentEvent));
      else failures.push("deployment audit events");
      if (approvalData.status === "fulfilled") setApprovals(list(approvalData.value));
      else failures.push("approval queue");
      setError(failures.length ? `Unavailable: ${failures.join(", ")}` : undefined);
      setLoading(false);
    });
    return () => controller.abort();
  }, [refreshKey]);

  const pending = approvals.filter((item) => ["PENDING", "REQUESTED", "AWAITING_APPROVAL"].includes(String(item.status ?? item.state).toUpperCase())).length;
  const persistentDrift = drift.filter((item) => item.persistent_drift).length;
  const healthy = drift.filter((item) => String(item.health_status).toUpperCase() === "HEALTHY").length;
  const pinned = drift.filter((item) => item.all_images_digest_pinned === true).length;
  const latestEvents = useMemo(() => events.slice(0, 20), [events]);

  return (
    <main className="page deployments-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">GitOps delivery</p>
          <h1>Deployments</h1>
          <p>Desired-versus-live state, promotion evidence, and deployment activity returned by the control plane.</p>
        </div>
        <div className="page-header__actions">
          {pending ? <Link to="/approvals" className="button button--primary">Review {pending} pending</Link> : null}
          <button type="button" className="button button--secondary" onClick={refresh} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button>
        </div>
      </header>

      <section className="summary-grid" aria-label="Deployment summary">
        <Summary label="Environments returned" value={String(drift.length)} detail="Staging and production" />
        <Summary label="Healthy" value={String(healthy)} detail="Argo CD health evidence" tone={healthy === drift.length && drift.length ? "good" : "neutral"} />
        <Summary label="Persistent drift" value={String(persistentDrift)} detail="Requires desired-state review" tone={persistentDrift ? "bad" : "good"} />
        <Summary label="Digest pinned" value={`${pinned}/${drift.length || "—"}`} detail="Immutable deployment evidence" tone={pinned === drift.length && drift.length ? "good" : "neutral"} />
      </section>

      {error ? <ErrorNotice title="Deployment evidence is incomplete" message={error} retry={refresh} /> : null}

      <section className="gitops-map" aria-labelledby="deployment-state-title">
        <header className="gitops-map__header">
          <div><p className="section-index">Desired state</p><h2 id="deployment-state-title">Environment reconciliation</h2></div>
          <p>No revision, sync state, or image policy result is inferred.</p>
        </header>
        {loading && !drift.length ? <LoadingPanel label="Loading GitOps state" /> : drift.length ? (
          <div className="gitops-map__environments">
            {drift.map((item) => (
              <article className="gitops-environment" key={item.environment}>
                <header>
                  <div><span className="gitops-environment__marker" aria-hidden="true" /><h3>{humanize(item.environment)}</h3><p>{item.application ?? "Application not returned"}</p></div>
                  <StatusBadge label={humanize(item.classification ?? item.sync_status)} tone={item.persistent_drift ? "bad" : stateTone(item.health_status)} dot />
                </header>
                <div className="gitops-environment__flow">
                  <div><span>Desired revision</span><code>{item.target_revision ?? "Unavailable"}</code></div>
                  <span className="gitops-environment__arrow" aria-hidden="true">→</span>
                  <div><span>Observed revision</span><code>{item.observed_revision ?? "Unavailable"}</code></div>
                </div>
                <dl>
                  <div><dt>Sync</dt><dd>{humanize(item.sync_status)}</dd></div>
                  <div><dt>Health</dt><dd>{humanize(item.health_status)}</dd></div>
                  <div><dt>Image policy</dt><dd>{item.all_images_digest_pinned === true ? "Digest pinned" : item.all_images_digest_pinned === false ? "Violation" : "Unavailable"}</dd></div>
                  <div><dt>Reconciled</dt><dd>{formatDate(item.reconciled_at)}</dd></div>
                </dl>
              </article>
            ))}
          </div>
        ) : <EmptyState title="GitOps state unavailable" detail="No desired-versus-live environment snapshot was returned." />}
      </section>

      <section className="audit-register" aria-labelledby="deployment-events-title">
        <header className="audit-register__header"><div><p className="section-index">Delivery evidence</p><h2 id="deployment-events-title">Deployment activity</h2></div><p>{latestEvents.length} matching audit records</p></header>
        {loading && !events.length ? <LoadingPanel label="Loading deployment activity" /> : latestEvents.length ? (
          <div className="table-scroll audit-register__table"><table className="data-table">
            <thead><tr><th>Recorded</th><th>Event</th><th>Actor</th><th>Action</th><th>Result</th><th>Evidence</th></tr></thead>
            <tbody>{latestEvents.map((event, index) => <tr key={event.id ?? index}>
              <td>{formatDate(event.timestamp ?? event.created_at)}</td>
              <td><strong>{humanize(event.event_type)}</strong></td>
              <td>{event.actor ?? "Not recorded"}</td>
              <td>{humanize(event.action)}</td>
              <td><StatusBadge label={humanize(event.result)} tone={stateTone(event.result)} /></td>
              <td><details className="audit-evidence"><summary>Inspect payload</summary><pre className="inline-data">{displayValue(event.event_metadata ?? event.metadata)}</pre></details></td>
            </tr>)}</tbody>
          </table></div>
        ) : <EmptyState title="No deployment activity" detail="No deployment, release, promotion, or GitOps audit records were returned." />}
      </section>
    </main>
  );
}

function Summary({ label, value, detail, tone = "neutral" }: { label: string; value: string; detail: string; tone?: "good" | "bad" | "neutral" }) {
  return <article className="summary-card" data-tone={tone}><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>;
}
