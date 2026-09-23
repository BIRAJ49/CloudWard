import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { IncidentTable } from "../components/incident-table";
import { EmptyState, ErrorNotice, LoadingPanel } from "../components/panel";
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
  const appliedFilters = [query, state !== "ALL", severity !== "ALL", service !== "ALL", environment !== "ALL", category !== "ALL", resolution !== "ALL", dateFrom, dateTo]
    .filter(Boolean).length;

  const clearFilters = () => {
    setQuery("");
    setState("ALL");
    setSeverity("ALL");
    setService("ALL");
    setEnvironment("ALL");
    setCategory("ALL");
    setResolution("ALL");
    setDateFrom("");
    setDateTo("");
  };

  return (
    <main className="page incident-register">
      <header className="register-header">
        <div>
          <p className="eyebrow">Operations desk / working register</p>
          <h1>Incidents</h1>
          <p>Every loaded case, with the controls operators use to find the next decision.</p>
        </div>
        <button type="button" className="button button--secondary" onClick={refresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh register"}
        </button>
      </header>

      <dl className="register-tally" role="region" aria-label="Loaded incident summary">
        <div><dt>Loaded</dt><dd>{incidents.length}</dd></div>
        <div className={active ? "register-tally__attention" : undefined}><dt>Active</dt><dd>{active}</dd></div>
        <div className={awaiting ? "register-tally__attention" : undefined}><dt>Awaiting approval</dt><dd>{awaiting}</dd></div>
        <div><dt>Terminal</dt><dd>{terminal}</dd><small>Resolved, blocked, or escalated</small></div>
      </dl>

      {error ? <ErrorNotice message={error} retry={refresh} /> : null}

      <section className="register-workbench" aria-labelledby="register-table-title">
        <form className="register-filter" role="search" onSubmit={(event) => event.preventDefault()}>
          <div className="register-filter__primary">
            <label className="field field--search">
              <span>Find a case</span>
              <input
                type="search"
                aria-label="Search incidents"
                placeholder="Search ID, title, service, type, environment"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            <label className="field"><span>Status</span><select value={state} onChange={(event) => setState(event.target.value)}><option value="ALL">Any status</option>{states.map((option) => <option key={option} value={option}>{humanize(option)}</option>)}</select></label>
            <label className="field"><span>Severity</span><select value={severity} onChange={(event) => setSeverity(event.target.value)}><option value="ALL">Any severity</option>{severities.map((option) => <option key={option} value={option}>{humanize(option)}</option>)}</select></label>
            <label className="field"><span>Service</span><select value={service} onChange={(event) => setService(event.target.value)}><option value="ALL">Any service</option>{serviceNames.map((option) => <option key={option} value={option}>{option}</option>)}</select></label>
          </div>

          <details className="register-filter__more" open={appliedFilters > 0 && Boolean(environment !== "ALL" || category !== "ALL" || resolution !== "ALL" || dateFrom || dateTo)}>
            <summary>More filters{appliedFilters > 0 ? ` · ${appliedFilters} applied` : ""}</summary>
            <div className="register-filter__secondary">
              <label className="field"><span>Environment</span><select value={environment} onChange={(event) => setEnvironment(event.target.value)}><option value="ALL">Any environment</option>{environments.map((option) => <option key={option} value={option}>{humanize(option)}</option>)}</select></label>
              <label className="field"><span>Category</span><select value={category} onChange={(event) => setCategory(event.target.value)}><option value="ALL">Any category</option>{categories.map((option) => <option key={option} value={option}>{humanize(option)}</option>)}</select></label>
              <label className="field"><span>Resolution</span><select value={resolution} onChange={(event) => setResolution(event.target.value)}><option value="ALL">Any source</option>{resolutions.map((option) => <option key={option} value={option}>{humanize(option)}</option>)}</select></label>
              <label className="field"><span>Created from</span><input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label>
              <label className="field"><span>Created through</span><input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label>
            </div>
          </details>

          <div className="register-filter__status">
            <p aria-live="polite"><strong>{filtered.length}</strong> of {incidents.length} loaded cases</p>
            {appliedFilters ? <button type="button" className="text-button" onClick={clearFilters}>Clear {appliedFilters} filter{appliedFilters === 1 ? "" : "s"}</button> : <span>Counts reflect API records only</span>}
          </div>
        </form>

        <div className="register-table-heading">
          <div><p className="eyebrow">Working set</p><h2 id="register-table-title">Incident ledger</h2></div>
          <span>Open a row to inspect evidence and decisions</span>
        </div>
        {loading ? <LoadingPanel label="Loading incidents" /> : filtered.length ? (
          <IncidentTable incidents={filtered} services={services} />
        ) : (
          <EmptyState
            title={incidents.length ? "No matching incidents" : "No incidents returned"}
            detail={incidents.length ? "Clear or change the active filters." : "The incident register is empty."}
          />
        )}
      </section>
    </main>
  );
}
