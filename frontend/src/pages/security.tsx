import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { EmptyState, ErrorNotice, LoadingPanel, Panel } from "../components/panel";
import { StatusBadge } from "../components/status-badge";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useControlPlaneEvents } from "../hooks/use-control-plane-events";
import { cloudWardApi } from "../lib/api";
import { displayValue, formatDate, humanize, stateTone } from "../lib/format";
import type { SecurityEvent, Tone } from "../types";

function eventItems(value: SecurityEvent[] | { items: SecurityEvent[] }): SecurityEvent[] {
  return Array.isArray(value) ? value : value.items;
}

function eventType(event: SecurityEvent): string {
  return event.classification ?? event.event_type ?? "SECURITY_EVENT";
}

function workloadName(event: SecurityEvent): string {
  return event.service_name ?? event.service ?? event.workload ?? event.pod_name ?? event.pod ?? "Unknown workload";
}

function severityTone(value?: string): Tone {
  const severity = value?.toUpperCase();
  if (severity === "CRITICAL" || severity === "HIGH") return "bad";
  if (severity === "MEDIUM" || severity === "WARNING") return "warn";
  if (severity === "LOW" || severity === "INFO") return "info";
  return "neutral";
}

function policySummary(value: SecurityEvent["policy_decision"]): { label: string; tone: Tone } {
  if (typeof value === "string") return { label: humanize(value), tone: stateTone(value) };
  if (!value) return { label: "Not evaluated", tone: "neutral" };
  if (value.requires_approval === true) return { label: "Approval required", tone: "warn" };
  if (value.allowed === true) return { label: "Allowed", tone: "good" };
  if (value.allowed === false) return { label: "Denied", tone: "bad" };
  return { label: humanize(String(value.decision ?? "Recorded")), tone: "info" };
}

export function SecurityPage() {
  useDocumentTitle("Security");
  const navigate = useNavigate();
  const location = useLocation();
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState("ALL");
  const [refreshKey, setRefreshKey] = useState(0);
  const [pendingAction, setPendingAction] = useState<string>();

  const refresh = useCallback(() => {
    setLoading(true);
    setError(undefined);
    setRefreshKey((value) => value + 1);
  }, []);

  useControlPlaneEvents(useCallback((event) => {
    const kind = String(event.type ?? event.event_type ?? "").toLowerCase();
    if (event.security_event_id || kind.includes("security") || kind.includes("containment")) {
      setRefreshKey((value) => value + 1);
    }
  }, []));

  useEffect(() => {
    const controller = new AbortController();
    cloudWardApi.securityEvents(controller.signal)
      .then((response) => {
        if (!controller.signal.aborted) setEvents(eventItems(response));
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        if (reason && typeof reason === "object" && "status" in reason && reason.status === 401) {
          navigate("/login", { replace: true, state: { from: location.pathname } });
          return;
        }
        setError(reason instanceof Error ? reason.message : "Unable to load runtime security events");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [location.pathname, navigate, refreshKey]);

  const filtered = useMemo(() => {
    const search = query.trim().toLowerCase();
    return events.filter((event) => {
      if (severity !== "ALL" && event.severity?.toUpperCase() !== severity) return false;
      if (!search) return true;
      return [eventType(event), workloadName(event), event.namespace, event.incident_id, event.summary]
        .some((value) => String(value ?? "").toLowerCase().includes(search));
    });
  }, [events, query, severity]);

  async function changeContainment(event: SecurityEvent, action: "apply" | "remove") {
    const key = `${event.id}:${action}`;
    setPendingAction(key);
    setError(undefined);
    try {
      await (action === "apply"
        ? await cloudWardApi.applyContainment(event.id)
        : await cloudWardApi.removeContainment(event.id));
      setRefreshKey((value) => value + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : `Unable to ${action} containment`);
    } finally {
      setPendingAction(undefined);
    }
  }

  const containedStates = new Set(["ACTIVE", "CONTAINED", "VERIFIED"]);
  const contained = events.filter((event) => containedStates.has(event.containment_status?.toUpperCase() ?? "")).length;
  const highSeverity = events.filter((event) => ["HIGH", "CRITICAL"].includes(event.severity?.toUpperCase() ?? "")).length;
  const linkedIncidents = new Set(events.map((event) => event.incident_id).filter(Boolean)).size;

  return (
    <div className="page security-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Runtime security</p>
          <h1>Security events</h1>
          <p>Tetragon detections normalized by CloudWard, with policy decisions and verified containment state.</p>
        </div>
        <button type="button" className="button button--secondary" onClick={refresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh events"}
        </button>
      </header>

      <div className="summary-grid" aria-label="Security event summary">
        <article className="summary-card"><span>Runtime events</span><strong>{events.length}</strong><small>Normalized detections</small></article>
        <article className={`summary-card ${highSeverity ? "summary-card--warn" : ""}`}><span>High severity</span><strong>{highSeverity}</strong><small>High and critical</small></article>
        <article className="summary-card"><span>Contained</span><strong>{contained}</strong><small>Verified active quarantines</small></article>
        <article className="summary-card"><span>Linked incidents</span><strong>{linkedIncidents}</strong><small>Using the shared state machine</small></article>
      </div>

      {error ? <ErrorNotice title="Security data unavailable" message={error} retry={refresh} /> : null}

      <Panel title="Runtime event register" description="Secret values and raw environment variables are redacted before events reach this view.">
        <div className="filter-bar">
          <label className="field field--search">
            <span>Search events</span>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Event, service, namespace, or incident" />
          </label>
          <label className="field">
            <span>Severity</span>
            <select value={severity} onChange={(event) => setSeverity(event.target.value)}>
              <option value="ALL">All severities</option>
              <option value="CRITICAL">Critical</option>
              <option value="HIGH">High</option>
              <option value="MEDIUM">Medium</option>
              <option value="LOW">Low</option>
              <option value="INFO">Info</option>
            </select>
          </label>
          <p className="result-count">{filtered.length} of {events.length} events</p>
        </div>

        {loading && !events.length ? <LoadingPanel label="Loading security events" /> : filtered.length ? (
          <div className="table-scroll">
            <table className="data-table security-table">
              <thead><tr><th>Event</th><th>Workload</th><th>Severity</th><th>Incident</th><th>Containment</th><th>Risk</th><th>OPA</th><th>Time</th><th><span className="visually-hidden">Action</span></th></tr></thead>
              <tbody>
                {filtered.map((event) => {
                  const policy = policySummary(event.policy_decision);
                  const isContained = containedStates.has(event.containment_status?.toUpperCase() ?? "");
                  const action = isContained ? "remove" : "apply";
                  return (
                    <tr key={event.id}>
                      <td><span className="cell-stack"><strong>{humanize(eventType(event))}</strong><small>{event.summary ?? event.id}</small></span></td>
                      <td><span className="cell-stack"><strong>{workloadName(event)}</strong><small>{event.namespace ?? "Unknown namespace"}</small></span></td>
                      <td><StatusBadge label={humanize(event.severity)} tone={severityTone(event.severity)} dot /></td>
                      <td>{event.incident_id ? <Link className="text-link" to={`/incidents/${event.incident_id}`}>Open incident</Link> : <span className="muted">Not linked</span>}</td>
                      <td><StatusBadge label={humanize(event.containment_status ?? "Not contained")} tone={isContained ? "good" : "neutral"} /></td>
                      <td><span className="risk-value">{typeof event.risk_score === "number" ? event.risk_score : "—"}{typeof event.risk_score === "number" ? <small>/100</small> : null}</span></td>
                      <td><StatusBadge label={policy.label} tone={policy.tone} /></td>
                      <td><time>{formatDate(event.occurred_at ?? event.created_at)}</time></td>
                      <td>
                        <button
                          type="button"
                          className="button button--quiet containment-action"
                          onClick={() => void changeContainment(event, action)}
                          disabled={pendingAction === `${event.id}:${action}` || !event.incident_id}
                          title={!event.incident_id ? "Containment requires a linked incident" : undefined}
                        >
                          {pendingAction === `${event.id}:${action}` ? "Working…" : isContained ? "Remove" : "Quarantine"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : <EmptyState title="No matching security events" detail="No normalized runtime events match the current filters." />}
      </Panel>

      <p className="security-boundary-note">Containment is namespace-scoped, policy-evaluated, reversible, and verified against the active Cilium policy before it is reported as applied.</p>
    </div>
  );
}
