import { useCallback, useEffect, useMemo, useState } from "react";
import { EmptyState, ErrorNotice, LoadingPanel, Panel } from "../components/panel";
import { useDocumentTitle } from "../hooks/use-document-title";
import { cloudWardApi } from "../lib/api";
import { displayValue, humanize, isActiveIncident, serviceName } from "../lib/format";
import type { Incident, Service } from "../types";

export function ServicesPage() {
  useDocumentTitle("Services");
  const [services, setServices] = useState<Service[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey((value) => value + 1), []);
  useEffect(() => { const controller = new AbortController(); setLoading(true); Promise.all([cloudWardApi.services(controller.signal), cloudWardApi.incidents(controller.signal)]).then(([serviceData, incidentData]) => { setServices(serviceData); setIncidents(incidentData); setError(undefined); }).catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Unable to load services"); }).finally(() => { if (!controller.signal.aborted) setLoading(false); }); return () => controller.abort(); }, [refreshKey]);
  const activeByService = useMemo(() => new Map(services.map((service) => [service.id, incidents.filter((incident) => isActiveIncident(incident) && (incident.service_id === service.id || serviceName(incident, services) === service.name)).length])), [incidents, services]);
  return <div className="page"><header className="page-header"><div><p className="eyebrow">Managed workloads</p><h1>Services</h1><p>Service ownership, deployment targets, criticality, and loaded active-incident counts.</p></div><button type="button" className="button button--secondary" onClick={refresh} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button></header>{error ? <ErrorNotice message={error} retry={refresh} /> : null}<Panel title="Service inventory" description="Incident counts apply only to the incident records returned by the API.">{loading && !services.length ? <LoadingPanel label="Loading services" /> : services.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>Service</th><th>Namespace</th><th>Deployment</th><th>Criticality</th><th>Active incidents</th><th>Labels</th></tr></thead><tbody>{services.map((service) => <tr key={service.id}><td><strong>{service.name}</strong></td><td><code>{service.namespace ?? "Not recorded"}</code></td><td><code>{service.deployment_name ?? "Not recorded"}</code></td><td>{humanize(service.criticality)}</td><td>{activeByService.get(service.id) ?? 0}</td><td><code>{displayValue(service.labels)}</code></td></tr>)}</tbody></table></div> : <EmptyState title="No services returned" detail="The service inventory is empty." />}</Panel></div>;
}
