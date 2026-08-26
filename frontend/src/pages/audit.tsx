import { useCallback, useEffect, useState } from "react";
import { EmptyState, ErrorNotice, LoadingPanel, Panel } from "../components/panel";
import { StatusBadge } from "../components/status-badge";
import { useControlPlaneEvents } from "../hooks/use-control-plane-events";
import { useDocumentTitle } from "../hooks/use-document-title";
import { cloudWardApi } from "../lib/api";
import { displayValue, formatDate, humanize, stateTone } from "../lib/format";
import type { AuditEvent } from "../types";

function items(value: AuditEvent[] | { items: AuditEvent[] }) {
  return Array.isArray(value) ? value : value.items;
}

export function AuditPage() {
  useDocumentTitle("Audit Log");
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey((value) => value + 1), []);

  useControlPlaneEvents(useCallback(() => refresh(), [refresh]));

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    cloudWardApi.audit(controller.signal)
      .then((value) => {
        setEvents(items(value));
        setError(undefined);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Unable to load audit events");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [refreshKey]);

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Accountability</p>
          <h1>Audit Log</h1>
          <p>Append-oriented records for model invocation, policy, approval, automation, notification, and verification events.</p>
        </div>
        <button type="button" className="button button--secondary" onClick={refresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>
      {error ? <ErrorNotice message={error} retry={refresh} /> : null}
      <Panel title="Control-plane audit" description={`${events.length} records returned; newest records are shown first.`}>
        {loading && !events.length ? <LoadingPanel label="Loading audit log" /> : events.length ? (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Time</th><th>Event</th><th>Actor</th><th>Action</th><th>Result</th><th>Details</th></tr></thead>
              <tbody>{events.map((event, index) => (
                <tr key={event.id ?? index}>
                  <td>{formatDate(event.timestamp ?? event.created_at)}</td>
                  <td><strong>{humanize(event.event_type)}</strong></td>
                  <td><span className="cell-stack"><strong>{event.actor ?? "Not recorded"}</strong><small>{humanize(event.actor_type)}</small></span></td>
                  <td>{humanize(event.action)}</td>
                  <td><StatusBadge label={humanize(event.result)} tone={stateTone(event.result)} /></td>
                  <td><details><summary>View</summary><pre className="inline-data">{displayValue(event.event_metadata ?? event.metadata)}</pre></details></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <EmptyState title="No audit records" detail="The audit API returned no events." />}
      </Panel>
    </div>
  );
}
