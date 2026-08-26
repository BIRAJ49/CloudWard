import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { IncidentTable } from "../components/incident-table";
import { EmptyState, ErrorNotice, LoadingPanel, Panel } from "../components/panel";
import { StatusBadge } from "../components/status-badge";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useControlPlaneEvents } from "../hooks/use-control-plane-events";
import { cloudWardApi } from "../lib/api";
import { humanize, isActiveIncident, normalizedCheck, stateTone } from "../lib/format";
import type { ApprovalRequest, AuditEvent, Cluster, FinOpsRecommendation, HealthResponse, Incident, SecurityEvent, Service, Tone } from "../types";

interface OverviewState {
  health?: HealthResponse;
  incidents: Incident[];
  clusters: Cluster[];
  services: Service[];
  securityEvents: SecurityEvent[];
  recommendations: FinOpsRecommendation[];
  approvals: ApprovalRequest[];
  audit: AuditEvent[];
  partialFailures: string[];
}

interface HealthItem {
  name: string;
  status: string;
  tone: Tone;
  detail: string;
  latencyMs?: number;
}

const initialState: OverviewState = { incidents: [], clusters: [], services: [], securityEvents: [], recommendations: [], approvals: [], audit: [], partialFailures: [] };

function unwrap<T>(value: T[] | { items: T[] }): T[] {
  return Array.isArray(value) ? value : value.items;
}

const workflow = [
  { label: "Event", detail: "Incident detected" },
  { label: "Evidence", detail: "Collect required signals" },
  { label: "Classify", detail: "Identify incident type" },
  { label: "Runbook", detail: "Match declarative procedure" },
  { label: "Diagnose", detail: "Deterministic signal checks" },
  { label: "Risk", detail: "Deterministic score" },
  { label: "OPA", detail: "Policy is final authority" },
  { label: "Approval", detail: "When policy requires it" },
  { label: "Action", detail: "Registered actions only" },
  { label: "Verify", detail: "Multi-signal proof" },
  { label: "Audit", detail: "Append the outcome" },
] as const;

function dependency(health: HealthResponse | undefined, names: string[]) {
  const checks = health?.dependencies ?? health?.checks ?? {};
  const key = Object.keys(checks).find((candidate) => names.includes(candidate.toLowerCase()));
  const check = key ? checks[key] : undefined;
  const normalized = normalizedCheck(check);
  const latencyMs = check && typeof check === "object" && "latency_ms" in check && typeof check.latency_ms === "number"
    ? check.latency_ms
    : undefined;
  return { ...normalized, latencyMs };
}

export function OverviewPage() {
  useDocumentTitle("Overview");
  const navigate = useNavigate();
  const location = useLocation();
  const [data, setData] = useState<OverviewState>(initialState);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

  const refresh = useCallback(() => {
    setLoading(true);
    setRefreshKey((key) => key + 1);
  }, []);

  useControlPlaneEvents(useCallback(() => refresh(), [refresh]));

  useEffect(() => {
    const controller = new AbortController();
    Promise.allSettled([
      cloudWardApi.health(controller.signal),
      cloudWardApi.incidents(controller.signal),
      cloudWardApi.clusters(controller.signal),
      cloudWardApi.services(controller.signal),
      cloudWardApi.securityEvents(controller.signal),
      cloudWardApi.finopsRecommendations(controller.signal),
      cloudWardApi.approvals(controller.signal),
      cloudWardApi.audit(controller.signal),
    ]).then(([health, incidents, clusters, services, security, recommendations, approvals, audit]) => {
      if (controller.signal.aborted) return;
      const protectedFailure = [incidents, clusters, services].some((result) => {
        if (result.status !== "rejected") return false;
        const reason: unknown = result.reason;
        return Boolean(reason && typeof reason === "object" && "status" in reason && reason.status === 401);
      });
      if (protectedFailure) {
        navigate("/login", { replace: true, state: { from: location.pathname } });
        return;
      }

      const failures: string[] = [];
      if (health.status === "rejected") failures.push("API health");
      if (incidents.status === "rejected") failures.push("incidents");
      if (clusters.status === "rejected") failures.push("cluster inventory");
      if (services.status === "rejected") failures.push("service inventory");
      if (security.status === "rejected") failures.push("runtime security");
      if (recommendations.status === "rejected") failures.push("FinOps");
      if (approvals.status === "rejected") failures.push("approvals");
      if (audit.status === "rejected") failures.push("audit activity");
      setData({
        health: health.status === "fulfilled" ? health.value : undefined,
        incidents: incidents.status === "fulfilled" ? incidents.value : [],
        clusters: clusters.status === "fulfilled" ? clusters.value : [],
        services: services.status === "fulfilled" ? services.value : [],
        securityEvents: security.status === "fulfilled" ? unwrap(security.value) : [],
        recommendations: recommendations.status === "fulfilled" ? unwrap(recommendations.value) : [],
        approvals: approvals.status === "fulfilled" ? unwrap(approvals.value) : [],
        audit: audit.status === "fulfilled" ? unwrap(audit.value) : [],
        partialFailures: failures,
      });
      setLoading(false);
    });
    return () => controller.abort();
  }, [location.pathname, navigate, refreshKey]);

  const activeIncidents = useMemo(
    () => data.incidents.filter(isActiveIncident).sort((left, right) => {
      const priority = (state: string) => state === "AWAITING_APPROVAL" ? 3 : ["EXECUTING", "VERIFYING", "ROLLBACK"].includes(state) ? 2 : 1;
      return priority(right.state) - priority(left.state) || (right.risk_score ?? -1) - (left.risk_score ?? -1);
    }),
    [data.incidents],
  );

  const api = data.health ? normalizedCheck(data.health.status ?? data.health.healthy) : normalizedCheck(undefined);
  const postgres = dependency(data.health, ["postgres", "postgresql", "database"]);
  const redis = dependency(data.health, ["redis"]);
  const opa = dependency(data.health, ["opa", "policy"]);
  const localCluster = data.clusters.find((cluster) =>
    cluster.environment?.toLowerCase() === "local" || cluster.name?.toLowerCase().includes("local"),
  ) ?? data.clusters[0];
  const cluster = localCluster ? normalizedCheck(localCluster.status ?? localCluster.connected) : normalizedCheck(undefined);

  const healthItems: HealthItem[] = [
    { name: "API", status: api.label, tone: api.tone, detail: data.health ? "Readiness endpoint" : "No health response" },
    { name: "PostgreSQL", status: postgres.label, tone: postgres.tone, detail: "Dependency check", latencyMs: postgres.latencyMs },
    { name: "Redis", status: redis.label, tone: redis.tone, detail: "Dependency check", latencyMs: redis.latencyMs },
    { name: "OPA", status: opa.label, tone: opa.tone, detail: "Policy dependency", latencyMs: opa.latencyMs },
    {
      name: "Local cluster",
      status: localCluster ? humanize(localCluster.status ?? "inventoried") : "Unavailable",
      tone: localCluster ? cluster.tone : "neutral",
      detail: localCluster?.name ?? "No cluster returned",
    },
    {
      name: "Open incidents",
      status: String(activeIncidents.length),
      tone: activeIncidents.length ? "warn" : "good",
      detail: `${activeIncidents.length} of ${data.incidents.length} loaded records`,
    },
  ];
  const awaitingApprovals = data.approvals.filter((item) => ["PENDING", "REQUESTED", "AWAITING_APPROVAL"].includes(String(item.status ?? item.state).toUpperCase())).length;
  const quarantined = data.securityEvents.filter((item) => ["CONTAINED", "ACTIVE", "VERIFIED"].includes(String(item.containment_status).toUpperCase())).length;
  const automaticRemediations = data.incidents.filter((item) => String(item.resolution_source).toUpperCase() === "CLOUDWARD_REMEDIATION").length;
  const severityCounts = data.incidents.reduce<Record<string, number>>((counts, item) => {
    const severity = String(item.severity ?? "UNKNOWN").toUpperCase();
    counts[severity] = (counts[severity] ?? 0) + 1;
    return counts;
  }, {});
  const savingsValues = data.recommendations.map((item) => {
    const observed = item.estimated_savings?.value;
    return item.estimated_monthly_savings ?? item.savings ?? (typeof observed === "number" ? observed : undefined);
  }).filter((value): value is number => typeof value === "number");
  const savings = savingsValues.length ? savingsValues.reduce((total, value) => total + value, 0) : undefined;
  const deployments = data.audit.filter((item) => /DEPLOY|GITOPS|RELEASE/.test(String(item.event_type).toUpperCase())).slice(0, 6);
  const pullRequests = data.audit.filter((item) => /PULL_REQUEST|_PR_/.test(String(item.event_type).toUpperCase())).slice(0, 6);
  const unavailable = (name: string) => data.partialFailures.includes(name);

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Local control plane</p>
          <h1>Overview</h1>
          <p>Current dependency health, incident workload, and remediation boundaries.</p>
        </div>
        <button type="button" className="button button--secondary" onClick={refresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      {data.partialFailures.length ? (
        <ErrorNotice
          title="Some operational data is unavailable"
          message={`Could not load ${data.partialFailures.join(", ")}. Unavailable values are not inferred.`}
          retry={refresh}
        />
      ) : null}

      <section className="status-grid" aria-label="Platform health">
        {healthItems.map((item) => (
          <article className="status-card" key={item.name}>
            <div className="status-card__top">
              <h2>{item.name}</h2>
              <span className={`health-dot health-dot--${item.tone}`} aria-hidden="true" />
            </div>
            <strong className="status-card__value">{item.status}</strong>
            <p>{item.detail}{typeof item.latencyMs === "number" ? ` · ${item.latencyMs.toFixed(1)} ms` : ""}</p>
          </article>
        ))}
      </section>

      <section className="operations-grid" aria-label="Operational summary">
        <OperationalStat label="Active incidents" value={unavailable("incidents") ? "Unavailable" : String(activeIncidents.length)} detail={`${data.incidents.length} loaded`} tone={activeIncidents.length ? "warn" : "good"} />
        <OperationalStat label="Incidents by severity" value={unavailable("incidents") ? "Unavailable" : Object.entries(severityCounts).map(([key, value]) => `${key} ${value}`).join(" · ") || "No incidents"} detail="Loaded records" />
        <OperationalStat label="Automatic remediations" value={unavailable("incidents") ? "Unavailable" : String(automaticRemediations)} detail="CloudWard resolution source" tone="info" />
        <OperationalStat label="Awaiting approval" value={unavailable("approvals") ? "Unavailable" : String(awaitingApprovals)} detail="Human decision required" tone={awaitingApprovals ? "warn" : "good"} />
        <OperationalStat label="Runtime security events" value={unavailable("runtime security") ? "Unavailable" : String(data.securityEvents.length)} detail="Loaded Tetragon records" />
        <OperationalStat label="Quarantined workloads" value={unavailable("runtime security") ? "Unavailable" : String(quarantined)} detail="Active verified containment" tone={quarantined ? "warn" : "good"} />
        <OperationalStat label="Estimated savings" value={unavailable("FinOps") || savings === undefined ? "Unavailable" : new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(savings)} detail="Observed local windows only" tone="info" />
        <OperationalStat label="Recent GitHub PRs" value={unavailable("audit activity") ? "Unavailable" : String(pullRequests.length)} detail="Loaded audit window" />
      </section>

      <div className="overview-grid">
        <Panel
          title="Active incidents"
          description={`${activeIncidents.length} unresolved records in the loaded incident set.`}
          action={<Link className="text-link" to="/incidents">View all incidents</Link>}
          className="overview-incidents"
        >
          {loading ? <LoadingPanel label="Loading incidents" /> : activeIncidents.length ? (
            <>
              <IncidentTable incidents={activeIncidents.slice(0, 6)} services={data.services} />
              {activeIncidents.length > 6 ? <p className="panel-footnote">Showing 6 of {activeIncidents.length} loaded active incidents.</p> : null}
            </>
          ) : <EmptyState title="No open incidents" detail="The incidents API returned no unresolved records." />}
        </Panel>

        <Panel title="Inventory" description="Clusters and services returned by the control-plane API." className="inventory-panel">
          <div className="inventory-section">
            <div className="section-heading"><h3>Clusters</h3><span>{data.clusters.length} loaded</span></div>
            {data.clusters.length ? (
              <ul className="inventory-list">
                {data.clusters.map((item) => (
                  <li key={item.id ?? item.name}>
                    <div><strong>{item.name ?? "Unnamed cluster"}</strong><small>{item.context_name ?? `${humanize(item.environment)} environment`}</small></div>
                    <StatusBadge label={humanize(item.status ?? "inventoried")} tone={stateTone(item.status)} dot />
                  </li>
                ))}
              </ul>
            ) : <p className="quiet-copy">No clusters were returned.</p>}
          </div>
          <div className="inventory-section">
            <div className="section-heading"><h3>Services</h3><span>{data.services.length} loaded</span></div>
            {data.services.length ? (
              <ul className="inventory-list">
                {data.services.map((service) => (
                  <li key={service.id}>
                    <div><strong>{service.name}</strong><small>{service.namespace ?? "Namespace not recorded"} · {service.deployment_name ?? "Deployment not recorded"}</small></div>
                    {service.criticality ? <span className="metadata-label">{humanize(service.criticality)}</span> : null}
                  </li>
                ))}
              </ul>
            ) : <p className="quiet-copy">No services were returned.</p>}
          </div>
        </Panel>
      </div>

      <div className="activity-grid">
        <Panel title="Recent deployments" description="Deployment and GitOps events from the audit log."><ActivityList events={deployments} empty="No deployment activity returned." /></Panel>
        <Panel title="Recent GitHub PRs" description="Pull-request automation events from the audit log."><ActivityList events={pullRequests} empty="No pull-request activity returned." /></Panel>
        <Panel title="Recent audit activity" description="Newest control-plane records in the loaded window."><ActivityList events={data.audit.slice(0, 6)} empty="No audit activity returned." /></Panel>
      </div>

      <Panel
        title="Deterministic remediation workflow"
        description="CloudWard follows this control path. AI can assist diagnosis, but it cannot authorize or execute an action."
        className="workflow-panel"
      >
        <ol className="workflow-list">
          {workflow.map((stage, index) => (
            <li key={stage.label}>
              <span>{index + 1}</span>
              <div><strong>{stage.label}</strong><small>{stage.detail}</small></div>
            </li>
          ))}
        </ol>
      </Panel>

      <section className="safety-boundary" aria-labelledby="safety-title">
        <div>
          <p className="eyebrow">Safety boundary</p>
          <h2 id="safety-title">Automation is constrained before execution</h2>
          <p>OPA evaluates every proposal and fails closed. Automatic remediation is limited to registered, reversible actions against explicitly labelled local or staging demo targets.</p>
        </div>
        <ul>
          <li>No arbitrary shell, kubectl, exec, or external HTTP actions</li>
          <li>Production, high-risk, and irreversible operations are denied or require escalation</li>
          <li>An incident resolves only after verification evidence is recorded</li>
        </ul>
      </section>
    </div>
  );
}

function OperationalStat({ label, value, detail, tone = "neutral" }: { label: string; value: string; detail: string; tone?: Tone }) {
  return <article className={`operation-stat operation-stat--${tone}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>;
}

function ActivityList({ events, empty }: { events: AuditEvent[]; empty: string }) {
  return events.length ? <ul className="activity-list">{events.map((event, index) => <li key={event.id ?? index}><div><strong>{humanize(event.event_type)}</strong><small>{event.actor ?? "Control plane"}</small></div><StatusBadge label={humanize(event.result)} tone={stateTone(event.result)} /></li>)}</ul> : <p className="quiet-copy">{empty}</p>;
}
