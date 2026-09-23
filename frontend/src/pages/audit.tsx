import { useCallback, useEffect, useState } from "react";
import { EmptyState, ErrorNotice, LoadingPanel } from "../components/panel";
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
  const refresh = useCallback(() => {
    setLoading(true);
    setError(undefined);
    setRefreshKey((value) => value + 1);
  }, []);

  useControlPlaneEvents(useCallback(() => refresh(), [refresh]));

  useEffect(() => {
    const controller = new AbortController();
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
    <div className="page audit-ledger">
      <header className="page-header audit-ledger__masthead">
        <div>
          <p className="eyebrow">Immutable control record</p>
          <h1>Audit ledger</h1>
          <p>The attributable sequence of model, policy, approval, automation, notification, and verification activity.</p>
        </div>
        <button type="button" className="button button--secondary" onClick={refresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh ledger"}
        </button>
      </header>

      <section className="audit-ledger__notice" aria-label="Audit record contract">
        <span className="audit-ledger__seal" aria-hidden="true">CW</span>
        <div><strong>Append-oriented record</strong><p>Returned events are presented newest first. Detail payloads remain attached to their originating control-plane action.</p></div>
        <p><strong>{events.length}</strong><span>records loaded</span></p>
      </section>

      {error ? <ErrorNotice message={error} retry={refresh} /> : null}
      <section className="audit-register" aria-labelledby="audit-register-title">
        <header className="audit-register__header"><div><p className="section-index">Chronology</p><h2 id="audit-register-title">Control-plane activity</h2></div><p>Newest record first</p></header>
        {loading && !events.length ? <LoadingPanel label="Loading audit log" /> : events.length ? (
          <div className="table-scroll audit-register__table">
            <table className="data-table">
              <thead><tr><th>Entry</th><th>Recorded</th><th>Event</th><th>Actor</th><th>Action</th><th>Result</th><th>Evidence</th></tr></thead>
              <tbody>{events.map((event, index) => (
                <tr key={event.id ?? index}>
                  <td><span className="audit-sequence">{String(events.length - index).padStart(4, "0")}</span></td>
                  <td>{formatDate(event.timestamp ?? event.created_at)}</td>
                  <td><strong className="audit-event-name">{humanize(event.event_type)}</strong></td>
                  <td><span className="cell-stack"><strong>{event.actor ?? "Not recorded"}</strong><small>{humanize(event.actor_type)}</small></span></td>
                  <td>{humanize(event.action)}</td>
                  <td><StatusBadge label={humanize(event.result)} tone={stateTone(event.result)} /></td>
                  <td><details className="audit-evidence"><summary>Inspect payload</summary><pre className="inline-data">{displayValue(event.event_metadata ?? event.metadata)}</pre></details></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <EmptyState title="No audit records" detail="The audit API returned no events." />}
      </section>
    </div>
  );
}
