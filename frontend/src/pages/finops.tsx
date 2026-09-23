import { useCallback, useEffect, useMemo, useState } from "react";
import { EmptyState, ErrorNotice, LoadingPanel, Panel } from "../components/panel";
import { StatusBadge } from "../components/status-badge";
import { useControlPlaneEvents } from "../hooks/use-control-plane-events";
import { useDocumentTitle } from "../hooks/use-document-title";
import { cloudWardApi } from "../lib/api";
import { displayValue, formatDate, humanize, stateTone } from "../lib/format";
import type { FinOpsRecommendation } from "../types";

function items(value: FinOpsRecommendation[] | { items: FinOpsRecommendation[] }) {
  return Array.isArray(value) ? value : value.items;
}

function money(value: number | null | undefined) {
  return typeof value === "number"
    ? new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value)
    : "Unavailable";
}

function saving(item: FinOpsRecommendation) {
  const observed = item.estimated_savings?.value;
  return item.estimated_monthly_savings ?? item.savings ?? (typeof observed === "number" ? observed : undefined);
}

function currentCost(item: FinOpsRecommendation) {
  const allocation = item.evidence?.allocation;
  if (!allocation || typeof allocation !== "object" || Array.isArray(allocation)) return item.current_monthly_cost ?? undefined;
  const value = (allocation as Record<string, unknown>).total_cost;
  return typeof value === "number" ? value : item.current_monthly_cost ?? undefined;
}

export function FinOpsPage() {
  useDocumentTitle("FinOps");
  const [recommendations, setRecommendations] = useState<FinOpsRecommendation[]>([]);
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
    if (kind.includes("finops") || kind.includes("recommendation")) refresh();
  }, [refresh]));

  useEffect(() => {
    const controller = new AbortController();
    cloudWardApi.finopsRecommendations(controller.signal)
      .then((value) => setRecommendations(items(value)))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Unable to load FinOps recommendations");
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refreshKey]);

  const summary = useMemo(() => {
    const current = recommendations.map(currentCost).filter((value): value is number => typeof value === "number");
    const clusterCurrent = recommendations.find((item) => item.recommendation_type === "NODE_EFFICIENCY");
    const clusterCurrentCost = clusterCurrent ? currentCost(clusterCurrent) : undefined;
    const savings = recommendations.map(saving).filter((value): value is number => typeof value === "number");
    return {
      current: clusterCurrentCost ?? (current.length === 1 ? current[0] : undefined),
      savings: savings.length ? savings.reduce((total, value) => total + value, 0) : undefined,
      open: recommendations.filter((item) => !["APPLIED", "REJECTED", "EXPIRED", "CLOSED"].includes(String(item.status ?? item.state).toUpperCase())).length,
      pr: recommendations.filter((item) => Boolean(item.github_pr_url ?? item.pr_url)).length,
    };
  }, [recommendations]);

  return (
    <div className="page finops-page">
      <header className="page-header">
        <div><p className="eyebrow">Evidence-based efficiency</p><h1>FinOps</h1><p>Deterministic Kubernetes cost recommendations. CloudWard does not infer savings when OpenCost or utilization data is unavailable.</p></div>
        <button type="button" className="button button--secondary" onClick={refresh} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button>
      </header>

      <section className="summary-grid" aria-label="FinOps summary">
        <Summary label="Current observed cost" value={money(summary.current)} detail="Local OpenCost evidence windows" />
        <Summary label="Potential observed savings" value={money(summary.savings)} detail="Not an AWS or monthly estimate" />
        <Summary label="Open recommendations" value={String(summary.open)} />
        <Summary label="GitHub PRs" value={String(summary.pr)} />
      </section>

      {error ? <ErrorNotice title="FinOps data unavailable" message={error} retry={refresh} /> : null}
      <Panel title="Workload recommendations" description="Current and recommended values are tied to a bounded evidence window and policy decision.">
        {loading && !recommendations.length ? <LoadingPanel label="Loading recommendations" /> : recommendations.length ? (
          <div className="table-scroll"><table className="data-table">
            <thead><tr><th>Workload</th><th>Current</th><th>Recommended</th><th>Savings</th><th>Risk</th><th>Confidence</th><th>Evidence window</th><th>Status</th><th>GitHub</th></tr></thead>
            <tbody>{recommendations.map((item) => {
              const status = String(item.status ?? item.state ?? "PROPOSED");
              return <tr key={item.id}>
                <td><span className="cell-stack"><strong>{item.workload ?? item.service ?? "Cluster capacity"}</strong><small>{item.namespace ?? item.cluster ?? humanize(item.recommendation_type ?? item.type)}</small></span></td>
                <td><code>{displayValue(item.current ?? item.current_config ?? item.current_monthly_cost)}</code></td>
                <td><code>{displayValue(item.recommended ?? item.recommended_config ?? item.recommended_monthly_cost)}</code></td>
                <td>{money(saving(item))}</td>
                <td>{typeof item.risk_score === "number" ? `${item.risk_score}/100` : "Not scored"}</td>
                <td>{displayValue(item.confidence)}</td>
                <td><span className="cell-stack"><strong>{formatDate(item.evidence_window_start)}</strong><small>to {formatDate(item.evidence_window_end)}</small></span></td>
                <td><StatusBadge label={humanize(status)} tone={stateTone(status)} dot /></td>
                <td>{(item.github_pr_url ?? item.pr_url) ? <a className="text-link" href={item.github_pr_url ?? item.pr_url ?? "#"} target="_blank" rel="noreferrer">Open PR</a> : <span className="muted">Not created</span>}</td>
              </tr>;
            })}</tbody>
          </table></div>
        ) : <EmptyState title="No recommendations" detail="No bounded recommendation was returned. Insufficient data does not produce estimated savings." />}
      </Panel>
    </div>
  );
}

function Summary({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return <article className="summary-card"><span>{label}</span><strong className="summary-card__compact">{value}</strong>{detail ? <small>{detail}</small> : null}</article>;
}
