import { useCallback, useEffect, useMemo, useState } from "react";
import { EmptyState, ErrorNotice, LoadingPanel } from "../components/panel";
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
  const refresh = useCallback(() => { setLoading(true); setError(undefined); setRefreshKey((value) => value + 1); }, []);
  useEffect(() => { const controller = new AbortController(); Promise.all([cloudWardApi.services(controller.signal), cloudWardApi.incidents(controller.signal)]).then(([serviceData, incidentData]) => { setServices(serviceData); setIncidents(incidentData); setError(undefined); }).catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Unable to load services"); }).finally(() => { if (!controller.signal.aborted) setLoading(false); }); return () => controller.abort(); }, [refreshKey]);
  const activeByService = useMemo(() => new Map(services.map((service) => [service.id, incidents.filter((incident) => isActiveIncident(incident) && (incident.service_id === service.id || serviceName(incident, services) === service.name)).length])), [incidents, services]);
  const activeIncidents = Array.from(activeByService.values()).reduce((total, count) => total + count, 0);
  const namespaces = new Set(services.map((service) => service.namespace).filter(Boolean)).size;

  return (
    <div className="page service-directory">
      <header className="page-header service-directory__masthead">
        <div><p className="eyebrow">Workload directory</p><h1>Services</h1><p>Where managed workloads live, how they deploy, and which ones currently demand operator attention.</p></div>
        <button type="button" className="button button--secondary" onClick={refresh} disabled={loading}>{loading ? "Refreshing…" : "Refresh directory"}</button>
      </header>

      <section className="directory-index" aria-label="Service directory index">
        <div><strong>{services.length}</strong><span>registered services</span></div>
        <div><strong>{namespaces}</strong><span>namespaces represented</span></div>
        <div className={activeIncidents ? "directory-index__attention" : undefined}><strong>{activeIncidents}</strong><span>loaded active incidents</span></div>
        <p>Incident totals apply only to records returned by the current API response.</p>
      </section>

      {error ? <ErrorNotice message={error} retry={refresh} /> : null}
      <section className="directory-ledger" aria-labelledby="service-directory-title">
        <header className="directory-ledger__header"><div><p className="section-index">Service register</p><h2 id="service-directory-title">Managed workloads</h2></div><p>Ownership and deployment coordinates</p></header>
        {loading && !services.length ? <LoadingPanel label="Loading services" /> : services.length ? (
          <div className="table-scroll directory-ledger__table"><table className="data-table">
            <thead><tr><th>Service</th><th>Namespace</th><th>Deployment target</th><th>Criticality</th><th>Active incidents</th><th>Inventory labels</th></tr></thead>
            <tbody>{services.map((service, index) => {
              const incidentCount = activeByService.get(service.id) ?? 0;
              return <tr key={service.id}>
                <td><span className="service-identity"><span className="service-identity__index">{String(index + 1).padStart(2, "0")}</span><strong>{service.name}</strong></span></td>
                <td><code>{service.namespace ?? "Not recorded"}</code></td>
                <td><code>{service.deployment_name ?? "Not recorded"}</code></td>
                <td><span className="service-criticality">{humanize(service.criticality)}</span></td>
                <td><strong className={incidentCount ? "service-incident-count service-incident-count--active" : "service-incident-count"}>{incidentCount}</strong></td>
                <td><code>{displayValue(service.labels)}</code></td>
              </tr>;
            })}</tbody>
          </table></div>
        ) : <EmptyState title="No services returned" detail="The service inventory is empty." />}
      </section>
    </div>
  );
}
