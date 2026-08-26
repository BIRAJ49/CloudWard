import { Link } from "react-router-dom";
import type { Incident, Service } from "../types";
import { formatDate, humanize, serviceName, stateTone } from "../lib/format";

function duration(incident: Incident): string {
  if (!incident.created_at) return "Unavailable";
  const start = new Date(incident.created_at).getTime();
  const end = new Date(incident.resolved_at ?? incident.updated_at ?? Date.now()).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return "Unavailable";
  const minutes = Math.floor((end - start) / 60_000);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? `${hours}h ${minutes % 60}m` : `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

export function IncidentTable({ incidents, services = [] }: { incidents: Incident[]; services?: Service[] }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption className="visually-hidden">CloudWard incidents returned by the API</caption>
        <thead>
          <tr>
            <th scope="col">Incident</th>
            <th scope="col">Service</th>
            <th scope="col">Category</th>
            <th scope="col">Severity</th>
            <th scope="col">Environment</th>
            <th scope="col">State</th>
            <th scope="col">Risk</th>
            <th scope="col">Created</th>
            <th scope="col">Duration</th>
            <th scope="col">Resolution</th>
          </tr>
        </thead>
        <tbody>
          {incidents.map((incident) => {
            const tone = stateTone(incident.state);
            return (
              <tr key={incident.id}>
                <td data-label="Incident">
                  <Link className="incident-link" to={`/incidents/${encodeURIComponent(incident.id)}`}>
                    <strong>{incident.title || humanize(incident.incident_type) || "Operational incident"}</strong>
                    <code>{incident.id}</code>
                  </Link>
                </td>
                <td data-label="Service"><span className="cell-stack"><strong>{serviceName(incident, services)}</strong><small>{incident.incident_type ? humanize(incident.incident_type) : "Type not recorded"}</small></span></td>
                <td data-label="Category">{humanize(String(incident.category ?? incident.incident_type ?? "Unknown"))}</td>
                <td data-label="Severity">{humanize(incident.severity)}</td>
                <td data-label="Environment"><span className="environment-label">{incident.environment ?? "Unknown"}</span></td>
                <td data-label="State">
                  <span className={`state-label state-label--${tone}`}><i aria-hidden="true" />{humanize(incident.state)}</span>
                </td>
                <td data-label="Risk">{typeof incident.risk_score === "number" ? <span className="risk-value">{incident.risk_score}<small>/100</small></span> : <span className="muted">Not scored</span>}</td>
                <td data-label="Created"><time>{formatDate(incident.created_at)}</time></td>
                <td data-label="Duration">{duration(incident)}</td>
                <td data-label="Resolution">{humanize(incident.resolution_source ?? "Pending")}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
