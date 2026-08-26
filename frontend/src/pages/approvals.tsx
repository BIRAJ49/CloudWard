import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { EmptyState, ErrorNotice, LoadingPanel, Panel } from "../components/panel";
import { StatusBadge } from "../components/status-badge";
import { useControlPlaneEvents } from "../hooks/use-control-plane-events";
import { useDocumentTitle } from "../hooks/use-document-title";
import { cloudWardApi } from "../lib/api";
import { displayValue, formatDate, humanize, stateTone } from "../lib/format";
import type { ApprovalRequest, Principal } from "../types";

function items(value: ApprovalRequest[] | { items: ApprovalRequest[] }) {
  return Array.isArray(value) ? value : value.items;
}

export function ApprovalsPage() {
  useDocumentTitle("Approvals");
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [principal, setPrincipal] = useState<Principal>();
  const [comments, setComments] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey((value) => value + 1), []);

  useControlPlaneEvents(useCallback((event) => {
    const kind = String(event.type ?? event.event_type ?? "").toLowerCase();
    if (kind.includes("approval")) refresh();
  }, [refresh]));

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    Promise.all([cloudWardApi.approvals(controller.signal), cloudWardApi.currentUser(controller.signal)])
      .then(([value, user]) => { setApprovals(items(value)); setPrincipal(user); setError(undefined); })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Unable to load approvals"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refreshKey]);

  async function decide(item: ApprovalRequest, decision: "approve" | "reject") {
    setPending(`${decision}:${item.id}`);
    setError(undefined);
    try {
      const updated = decision === "approve"
        ? await cloudWardApi.approve(item.id, comments[item.id] ?? "")
        : await cloudWardApi.reject(item.id, comments[item.id] ?? "");
      setApprovals((current) => current.map((value) => value.id === updated.id ? updated : value));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : `Unable to ${decision} action`);
    } finally {
      setPending(undefined);
    }
  }

  const canDecide = principal?.role === "Operator" || principal?.role === "Admin";

  return <div className="page">
    <header className="page-header"><div><p className="eyebrow">Human control point</p><h1>Approvals</h1><p>Review actions that policy has held for an explicit operator decision. Approval does not bypass stale-action or execution safeguards.</p></div><button type="button" className="button button--secondary" onClick={refresh} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button></header>
    {!canDecide && principal ? <ErrorNotice title="Read-only approval queue" message="Viewer sessions can inspect decisions but cannot approve or reject actions." /> : null}
    {error ? <ErrorNotice message={error} retry={refresh} /> : null}
    <Panel title="Approval queue" description={`${approvals.length} durable approval records returned by the control plane.`}>
      {loading && !approvals.length ? <LoadingPanel label="Loading approval queue" /> : approvals.length ? <div className="approval-list">{approvals.map((item) => {
        const status = String(item.status ?? item.state ?? item.decision ?? "PENDING");
        const open = ["PENDING", "AWAITING_APPROVAL", "REQUESTED"].includes(status.toUpperCase());
        return <article className="approval-record" key={item.id}>
          <header><div><StatusBadge label={humanize(status)} tone={stateTone(status)} dot /><h2>{humanize(item.action_type ?? item.action ?? "Proposed action")}</h2></div><time>{formatDate(item.created_at)}</time></header>
          <dl className="record-grid">
            <div><dt>Incident</dt><dd>{item.incident_id ? <Link className="text-link" to={`/incidents/${item.incident_id}`}>{item.incident_id}</Link> : "Not linked"}</dd></div>
            <div><dt>Environment</dt><dd>{humanize(item.environment)}</dd></div>
            <div><dt>Risk</dt><dd>{typeof item.risk_score === "number" ? `${item.risk_score}/100` : "Not scored"}</dd></div>
            <div><dt>Blast radius</dt><dd>{displayValue(item.blast_radius)}</dd></div>
            <div><dt>Reversible</dt><dd>{item.reversible === true ? "Yes" : item.reversible === false ? "No" : "Not recorded"}</dd></div>
            <div><dt>Requested by</dt><dd>{item.requested_by ?? "Control plane"}</dd></div>
            <div><dt>Runbook</dt><dd>{displayValue(item.runbook)}</dd></div>
            <div><dt>Expires</dt><dd>{formatDate(item.expires_at)}</dd></div>
          </dl>
          {item.reason ? <p className="record-reason"><strong>Reason</strong>{item.reason}</p> : null}
          {open ? <div className="approval-controls"><label className="field"><span>Decision comment</span><input value={comments[item.id] ?? ""} onChange={(event) => setComments((current) => ({ ...current, [item.id]: event.target.value }))} placeholder="Operator rationale" disabled={!canDecide || Boolean(pending)} /></label><div><button type="button" className="button button--secondary" disabled={!canDecide || Boolean(pending)} onClick={() => void decide(item, "reject")}>Reject</button><button type="button" className="button button--primary" disabled={!canDecide || Boolean(pending)} onClick={() => void decide(item, "approve")}>Approve</button></div></div> : <p className="decision-record">Decision by {item.approver ?? item.decided_by ?? "control plane"} at {formatDate(item.decided_at)}{(item.comment ?? item.decision_comment) ? ` — ${item.comment ?? item.decision_comment}` : ""}</p>}
        </article>;
      })}</div> : <EmptyState title="No approval records" detail="No action currently requires or has received a human decision." />}
    </Panel>
  </div>;
}
