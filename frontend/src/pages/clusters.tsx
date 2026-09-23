import { useCallback, useEffect, useState } from "react";
import { EmptyState, ErrorNotice, LoadingPanel } from "../components/panel";
import { StatusBadge } from "../components/status-badge";
import { useControlPlaneEvents } from "../hooks/use-control-plane-events";
import { useDocumentTitle } from "../hooks/use-document-title";
import { cloudWardApi } from "../lib/api";
import { displayValue, formatDate, humanize, stateTone } from "../lib/format";
import type { Cluster, GitOpsDrift } from "../types";

export function ClustersPage() {
  useDocumentTitle("Clusters");
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [drift, setDrift] = useState<GitOpsDrift[]>([]);
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
    if (kind.includes("gitops") || kind.includes("deployment") || kind === "cluster.observation") refresh();
  }, [refresh]));

  useEffect(() => {
    // An offline agent emits no events; periodically re-evaluate server-side freshness.
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "hidden") refresh();
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    const controller = new AbortController();
    Promise.allSettled([
      cloudWardApi.clusters(controller.signal),
      cloudWardApi.gitopsDrift("staging", controller.signal),
      cloudWardApi.gitopsDrift("production", controller.signal),
    ]).then(([inventory, staging, production]) => {
      if (controller.signal.aborted) return;
      const failures: string[] = [];
      if (inventory.status === "fulfilled") setClusters(inventory.value);
      else failures.push("cluster inventory");
      setDrift([staging, production].flatMap((result) => result.status === "fulfilled" ? [result.value] : []));
      if (staging.status === "rejected") failures.push("staging drift");
      if (production.status === "rejected") failures.push("production drift");
      setError(failures.length ? `Unavailable: ${failures.join(", ")}` : undefined);
      setLoading(false);
    });
    return () => controller.abort();
  }, [refreshKey]);

  const connected = clusters.filter((cluster) => cluster.connected || String(cluster.status).toUpperCase() === "CONNECTED").length;
  const persistentDrift = drift.filter((item) => item.persistent_drift).length;

  return (
    <div className="page topology-inventory">
      <header className="page-header topology-inventory__masthead">
        <div><p className="eyebrow">Fleet topology</p><h1>Clusters</h1><p>Registered control contexts and the desired-versus-live GitOps boundary for staging and production.</p></div>
        <button type="button" className="button button--secondary" onClick={refresh} disabled={loading}>{loading ? "Refreshing…" : "Refresh topology"}</button>
      </header>

      <section className="topology-pulse" aria-label="Fleet topology status">
        <div><span>Registered</span><strong>{clusters.length}</strong></div>
        <div><span>Connected</span><strong>{connected}</strong></div>
        <div><span>GitOps snapshots</span><strong>{drift.length}<small>/2</small></strong></div>
        <div className={persistentDrift ? "topology-pulse__alert" : undefined}><span>Persistent drift</span><strong>{persistentDrift}</strong></div>
        <p>Topology is reported, never inferred. Missing inventory and Argo CD snapshots remain visibly unavailable.</p>
      </section>

      {error ? <ErrorNotice message={error} retry={refresh} /> : null}

      <section className="topology-sheet" aria-labelledby="cluster-inventory-title">
        <header className="topology-sheet__header"><div><p className="section-index">01 / Control contexts</p><h2 id="cluster-inventory-title">Cluster inventory</h2></div><p>Connection records from the control plane</p></header>
        {loading && !clusters.length ? <LoadingPanel label="Loading clusters" /> : clusters.length ? (
          <div className="table-scroll topology-sheet__table"><table className="data-table">
            <thead><tr><th>Cluster</th><th>Environment</th><th>Status</th><th>Context</th><th>Labels</th><th>Updated</th></tr></thead>
            <tbody>{clusters.map((cluster) => {
              const status = String(cluster.status ?? (cluster.connected ? "CONNECTED" : "UNKNOWN"));
              return <tr key={cluster.id ?? cluster.name}><td><span className="cluster-identity"><span aria-hidden="true" className="cluster-identity__node" /><strong>{cluster.name ?? "Unnamed cluster"}</strong></span></td><td>{humanize(cluster.environment)}</td><td><StatusBadge label={humanize(status)} tone={stateTone(status)} dot /></td><td><code>{cluster.context_name ?? "Not returned"}</code></td><td><code>{displayValue(cluster.labels)}</code></td><td>{formatDate(cluster.agent_observed_at ?? cluster.updated_at ?? cluster.created_at)}{cluster.agent_observed_at ? <small>Agent observation</small> : null}</td></tr>;
            })}</tbody>
          </table></div>
        ) : <EmptyState title="No clusters returned" detail="The cluster inventory is empty." />}
      </section>

      <section className="gitops-map" aria-labelledby="gitops-map-title">
        <header className="gitops-map__header"><div><p className="section-index">02 / Reconciliation boundary</p><h2 id="gitops-map-title">GitOps drift</h2></div><p>Temporary runtime operations are classified separately from persistent desired-state drift.</p></header>
        {drift.length ? <div className="gitops-map__environments">
          {drift.map((item) => <article className="gitops-environment" key={item.environment}>
            <header><div><span className="gitops-environment__marker" aria-hidden="true" /><h3>{humanize(item.environment)}</h3><p>{item.application ?? "Application unavailable"}</p></div><StatusBadge label={humanize(item.classification)} tone={item.persistent_drift ? "bad" : "good"} dot /></header>
            <div className="gitops-environment__flow" aria-label={`${humanize(item.environment)} desired and live revisions`}>
              <div><span>Desired</span><code>{item.target_revision ?? "Unavailable"}</code></div>
              <span className="gitops-environment__arrow" aria-hidden="true">→</span>
              <div><span>Live</span><code>{item.observed_revision ?? "Unavailable"}</code></div>
            </div>
            <dl>
              <div><dt>Sync</dt><dd>{humanize(item.sync_status)}</dd></div>
              <div><dt>Health</dt><dd>{humanize(item.health_status)}</dd></div>
              <div><dt>Image policy</dt><dd>{item.all_images_digest_pinned ? "Digest pinned" : "Violation"}</dd></div>
              <div><dt>Reconciled</dt><dd>{formatDate(item.reconciled_at)}</dd></div>
            </dl>
          </article>)}
        </div> : <EmptyState title="Drift status unavailable" detail="No Argo CD desired-versus-live snapshot was returned." />}
      </section>
    </div>
  );
}
