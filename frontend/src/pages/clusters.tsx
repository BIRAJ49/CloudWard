import { useCallback, useEffect, useState } from "react";
import { EmptyState, ErrorNotice, LoadingPanel, Panel } from "../components/panel";
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
  const refresh = useCallback(() => setRefreshKey((value) => value + 1), []);

  useControlPlaneEvents(useCallback((event) => {
    const kind = String(event.type ?? event.event_type ?? "").toLowerCase();
    if (kind.includes("gitops") || kind.includes("deployment")) refresh();
  }, [refresh]));

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
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

  return (
    <div className="page">
      <header className="page-header">
        <div><p className="eyebrow">Inventory and desired state</p><h1>Clusters</h1><p>Connected cluster records plus factual Argo CD desired-versus-live state for staging and production.</p></div>
        <button type="button" className="button button--secondary" onClick={refresh} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button>
      </header>
      {error ? <ErrorNotice message={error} retry={refresh} /> : null}
      <Panel title="Cluster inventory" description="No health or capacity values are inferred when inventory is unavailable.">
        {loading && !clusters.length ? <LoadingPanel label="Loading clusters" /> : clusters.length ? (
          <div className="table-scroll"><table className="data-table">
            <thead><tr><th>Cluster</th><th>Environment</th><th>Status</th><th>Context</th><th>Labels</th><th>Updated</th></tr></thead>
            <tbody>{clusters.map((cluster) => {
              const status = String(cluster.status ?? (cluster.connected ? "CONNECTED" : "UNKNOWN"));
              return <tr key={cluster.id ?? cluster.name}><td><strong>{cluster.name ?? "Unnamed cluster"}</strong></td><td>{humanize(cluster.environment)}</td><td><StatusBadge label={humanize(status)} tone={stateTone(status)} dot /></td><td><code>{cluster.context_name ?? "Not returned"}</code></td><td><code>{displayValue(cluster.labels)}</code></td><td>{formatDate(cluster.updated_at ?? cluster.created_at)}</td></tr>;
            })}</tbody>
          </table></div>
        ) : <EmptyState title="No clusters returned" detail="The cluster inventory is empty." />}
      </Panel>
      <Panel title="GitOps drift" description="Temporary runtime operations are classified separately from persistent desired-state drift.">
        {drift.length ? <div className="table-scroll"><table className="data-table">
          <thead><tr><th>Environment</th><th>Application</th><th>Sync / health</th><th>Target revision</th><th>Observed revision</th><th>Image policy</th><th>Classification</th><th>Reconciled</th></tr></thead>
          <tbody>{drift.map((item) => <tr key={item.environment}><td><strong>{humanize(item.environment)}</strong></td><td>{item.application ?? "Unavailable"}</td><td><span className="cell-stack"><strong>{humanize(item.sync_status)}</strong><small>{humanize(item.health_status)}</small></span></td><td><code>{item.target_revision ?? "Unavailable"}</code></td><td><code>{item.observed_revision ?? "Unavailable"}</code></td><td><StatusBadge label={item.all_images_digest_pinned ? "Digest pinned" : "Violation"} tone={item.all_images_digest_pinned ? "good" : "bad"} /></td><td><StatusBadge label={humanize(item.classification)} tone={item.persistent_drift ? "bad" : "good"} dot /></td><td>{formatDate(item.reconciled_at)}</td></tr>)}</tbody>
        </table></div> : <EmptyState title="Drift status unavailable" detail="No Argo CD desired-versus-live snapshot was returned." />}
      </Panel>
    </div>
  );
}
