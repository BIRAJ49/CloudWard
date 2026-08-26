import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { IncidentTable } from "../components/incident-table";
import { EmptyState, ErrorNotice, LoadingPanel, Panel } from "../components/panel";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useControlPlaneEvents } from "../hooks/use-control-plane-events";
import { cloudWardApi } from "../lib/api";
import { humanize, isActiveIncident, serviceName } from "../lib/format";
import type { Incident, Service } from "../types";

export function IncidentsPage() {
  useDocumentTitle("Incidents");
  const navigate = useNavigate();
  const location = useLocation();
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [query, setQuery] = useState("");
  const [state, setState] = useState("ALL");
  const [severity, setSeverity] = useState("ALL");
  const [service, setService] = useState("ALL");
  const [environment, setEnvironment] = useState("ALL");
  const [category, setCategory] = useState("ALL");
  const [resolution, setResolution] = useState("ALL");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const refresh = useCallback(() => {
    setLoading(true);
    setError(undefined);
    setRefreshKey((key) => key + 1);
  }, []);

  useControlPlaneEvents(useCallback((event) => {
    const kind = String(event.type ?? event.event_type ?? "").toLowerCase();
    if (kind.includes("incident") || kind.includes("remediation") || kind.includes("verification")) refresh();
  }, [refresh]));

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([cloudWardApi.incidents(controller.signal), cloudWardApi.services(controller.signal)])
      .then(([incidentData, serviceData]) => {
        setIncidents(incidentData);
        setServices(serviceData);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          if (reason && typeof reason === "object" && "status" in reason && reason.status === 401) {
            navigate("/login", { replace: true, state: { from: location.pathname } });
            return;
          }
          setError(reason instanceof Error ? reason.message : "Unable to load incidents");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [location.pathname, navigate, refreshKey]);

  const states = useMemo(() => [...new Set(incidents.map((incident) => incident.state))].sort(), [incidents]);
  const severities = useMemo(() => [...new Set(incidents.map((incident) => incident.severity).filter((value): value is string => Boolean(value)))].sort(), [incidents]);
  const serviceNames = useMemo(() => [...new Set(incidents.map((incident) => serviceName(incident, services)))].sort(), [incidents, services]);
  const environments = useMemo(() => [...new Set(incidents.map((incident) => incident.environment).filter((value): value is string => Boolean(value)))].sort(), [incidents]);
  const categories = useMemo(() => [...new Set(incidents.map((incident) => String(incident.category ?? incident.incident_type ?? "")).filter(Boolean))].sort(), [incidents]);
  const resolutions = useMemo(() => [...new Set(incidents.map((incident) => incident.resolution_source).filter((value): value is string => Boolean(value)))].sort(), [incidents]);
  const filtered = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return incidents.filter((incident) => {
      const matchesQuery = !normalizedQuery || [
        incident.id,
        incident.title,
        incident.incident_type,
        serviceName(incident, services),
        incident.environment,
      ].filter(Boolean).some((value) => String(value).toLowerCase().includes(normalizedQuery));
      const created = incident.created_at ? new Date(incident.created_at).getTime() : undefined;
      const from = dateFrom ? new Date(`${dateFrom}T00:00:00`).getTime() : undefined;
      const to = dateTo ? new Date(`${dateTo}T23:59:59.999`).getTime() : undefined;
      return matchesQuery
        && (state === "ALL" || incident.state === state)
        && (severity === "ALL" || incident.severity === severity)
        && (service === "ALL" || serviceName(incident, services) === service)
        && (environment === "ALL" || incident.environment === environment)
        && (category === "ALL" || String(incident.category ?? incident.incident_type) === category)
        && (resolution === "ALL" || incident.resolution_source === resolution)
        && (from === undefined || (created !== undefined && created >= from))
        && (to === undefined || (created !== undefined && created <= to));
    });
  }, [category, dateFrom, dateTo, environment, incidents, query, resolution, service, services, severity, state]);

  const active = incidents.filter(isActiveIncident).length;
  const awaiting = incidents.filter((incident) => incident.state === "AWAITING_APPROVAL").length;
  const terminal = incidents.filter((incident) => ["RESOLVED", "BLOCKED", "ESCALATED"].includes(incident.state)).length;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Operational records</p>
          <h1>Incidents</h1>
          <p>Evidence, decisions, actions, verification, and audit history for loaded incidents.</p>
        </div>
        <button type="button" className="button button--secondary" onClick={refresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      <section className="summary-grid" aria-label="Loaded incident summary">
        <Summary label="Loaded records" value={incidents.length} />
        <Summary label="Active" value={active} />
        <Summary label="Awaiting approval" value={awaiting} tone={awaiting ? "warn" : undefined} />
        <Summary label="Terminal" value={terminal} detail="Resolved, blocked, or escalated" />
      </section>

      {error ? <ErrorNotice message={error} retry={refresh} /> : null}

      <Panel title="Incident register" description="Counts and filters apply only to records returned by the API.">
        <form className="filter-bar" role="search" onSubmit={(event) => event.preventDefault()}>
          <label className="field field--search">
            <span>Search incidents</span>
            <input
              type="search"
              aria-label="Search incidents"
              placeholder="ID, title, service, type, or environment"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <label className="field">
            <span>Status</span>
            <select value={state} onChange={(event) => setState(event.target.value)}>
              <option value="ALL">All states</option>
              {states.map((option) => <option key={option} value={option}>{humanize(option)}</option>)}
            </select>
          </label>
          <label className="field"><span>Severity</span><select value={severity} onChange={(event) => setSeverity(event.target.value)}><option value="ALL">All severities</option>{severities.map((option) => <option key={option} value={option}>{humanize(option)}</option>)}</select></label>
          <label className="field"><span>Service</span><select value={service} onChange={(event) => setService(event.target.value)}><option value="ALL">All services</option>{serviceNames.map((option) => <option key={option} value={option}>{option}</option>)}</select></label>
          <label className="field"><span>Environment</span><select value={environment} onChange={(event) => setEnvironment(event.target.value)}><option value="ALL">All environments</option>{environments.map((option) => <option key={option} value={option}>{humanize(option)}</option>)}</select></label>
          <label className="field"><span>Category</span><select value={category} onChange={(event) => setCategory(event.target.value)}><option value="ALL">All categories</option>{categories.map((option) => <option key={option} value={option}>{humanize(option)}</option>)}</select></label>
          <label className="field"><span>Resolution</span><select value={resolution} onChange={(event) => setResolution(event.target.value)}><option value="ALL">All sources</option>{resolutions.map((option) => <option key={option} value={option}>{humanize(option)}</option>)}</select></label>
          <label className="field"><span>Created from</span><input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label>
          <label className="field"><span>Created through</span><input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label>
          <p className="result-count" aria-live="polite">Showing {filtered.length} of {incidents.length} loaded</p>
        </form>

        {loading ? <LoadingPanel label="Loading incidents" /> : filtered.length ? (
          <IncidentTable incidents={filtered} services={services} />
        ) : (
          <EmptyState
            title={incidents.length ? "No matching incidents" : "No incidents returned"}
            detail={incidents.length ? "Change the search text or state filter." : "The incident register is empty."}
          />
        )}
      </Panel>
    </div>
  );
}

function Summary({ label, value, detail, tone }: { label: string; value: number; detail?: string; tone?: "warn" }) {
  return (
    <article className={`summary-card ${tone ? `summary-card--${tone}` : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </article>
  );
}
