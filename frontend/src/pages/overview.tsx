import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { IncidentTable } from "../components/incident-table";
import { Icon } from "../components/icon";
import { DottedGrid } from "../components/obsidian/dotted-grid";
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

const initialState: OverviewState = {
  incidents: [],
  clusters: [],
  services: [],
  securityEvents: [],
  recommendations: [],
  approvals: [],
  audit: [],
  partialFailures: [],
};

const workflow = [
  { label: "Event", detail: "Detected" },
  { label: "Evidence", detail: "Collected" },
  { label: "Runbook", detail: "Matched" },
  { label: "Risk", detail: "Scored" },
  { label: "OPA", detail: "Decides" },
  { label: "Approval", detail: "When required" },
  { label: "Action", detail: "Allowlisted" },
  { label: "Verify", detail: "Proven" },
  { label: "Audit", detail: "Recorded" },
] as const;

function unwrap<T>(value: T[] | { items: T[] }): T[] {
  return Array.isArray(value) ? value : value.items;
}

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
  const localCluster = data.clusters.find((item) =>
    item.environment?.toLowerCase() === "local" || item.name?.toLowerCase().includes("local"),
  ) ?? data.clusters[0];
  const cluster = localCluster ? normalizedCheck(localCluster.status ?? localCluster.connected) : normalizedCheck(undefined);

  const healthItems: HealthItem[] = [
    { name: "API", status: api.label, tone: api.tone, detail: data.health ? "Readiness endpoint" : "No health response" },
    { name: "PostgreSQL", status: postgres.label, tone: postgres.tone, detail: "Control-plane record", latencyMs: postgres.latencyMs },
    { name: "Redis", status: redis.label, tone: redis.tone, detail: "Queue and event broker", latencyMs: redis.latencyMs },
    { name: "OPA", status: opa.label, tone: opa.tone, detail: "Policy authority", latencyMs: opa.latencyMs },
    {
      name: "Cluster",
      status: localCluster ? humanize(localCluster.status ?? "inventoried") : "Unavailable",
      tone: localCluster ? cluster.tone : "neutral",
      detail: localCluster?.name ?? "No cluster returned",
    },
    {
      name: "Open incidents",
      status: data.partialFailures.includes("incidents") ? "Unavailable" : String(activeIncidents.length),
      tone: activeIncidents.length ? "warn" : data.partialFailures.includes("incidents") ? "neutral" : "good",
      detail: `${data.incidents.length} loaded records`,
    },
  ];

  const awaitingApprovals = data.approvals.filter((item) => ["PENDING", "REQUESTED", "AWAITING_APPROVAL"].includes(String(item.status ?? item.state).toUpperCase())).length;
  const savingsValues = data.recommendations.map((item) => {
    const observed = item.estimated_savings?.value;
    return item.estimated_monthly_savings ?? item.savings ?? (typeof observed === "number" ? observed : undefined);
  }).filter((value): value is number => typeof value === "number");
  const savings = savingsValues.length ? savingsValues.reduce((total, value) => total + value, 0) : undefined;
  const deployments = data.audit.filter((item) => /DEPLOY|GITOPS|RELEASE/.test(String(item.event_type).toUpperCase())).slice(0, 6);
  const pullRequests = data.audit.filter((item) => /PULL_REQUEST|_PR_/.test(String(item.event_type).toUpperCase())).slice(0, 6);
  const unavailable = (name: string) => data.partialFailures.includes(name);

  const heroState = loading
    ? { label: "Synchronizing control plane", tone: "neutral" as Tone, detail: "Waiting for current API evidence" }
    : data.partialFailures.length
      ? { label: "Partial visibility", tone: "warn" as Tone, detail: `${data.partialFailures.length} data source${data.partialFailures.length === 1 ? " is" : "s are"} unavailable` }
      : activeIncidents.length
        ? { label: "Operator attention", tone: "warn" as Tone, detail: `${activeIncidents.length} active incident${activeIncidents.length === 1 ? "" : "s"} in the loaded window` }
        : { label: "No active incidents", tone: "good" as Tone, detail: "All loaded incident records are terminal" };

  return (
    <div className="page overview-page">
      <header className="overview-heading">
        <div>
          <p className="eyebrow">Operations dashboard</p>
          <h1 id="overview-title">Overview</h1>
          <p>Live reliability, security, cost, and policy evidence across the control plane.</p>
        </div>
        <div className="overview-heading__actions">
          <Link className="button button--secondary" to="/incident-lab"><Icon name="lab" />Incident lab</Link>
          <button type="button" className="button button--primary" onClick={refresh} disabled={loading}>
            <Icon name="refresh" className={loading ? "is-spinning" : undefined} />
            {loading ? "Refreshing…" : "Refresh data"}
          </button>
        </div>
      </header>

      <section className={`operating-state operating-state--${heroState.tone}`} aria-label="Current operating state">
        <DottedGrid className="operating-state__grid" paused={loading} />
        <div className="operating-state__icon"><Icon name={heroState.tone === "good" ? "check" : "incidents"} /></div>
        <div className="operating-state__copy">
          <span>Current operating state</span>
          <h2>{heroState.label}</h2>
          <p>{heroState.detail}. Evidence is live and no missing values are inferred.</p>
        </div>
        <div className="operating-state__boundary">
          <Icon name="shield" />
          <div><span>Decision authority</span><strong>OPA enforced</strong><small>AI is advisory only</small></div>
        </div>
      </section>

      {data.partialFailures.length ? (
        <ErrorNotice
          title="Some operational data is unavailable"
          message={`Could not load ${data.partialFailures.join(", ")}. Unavailable values are not inferred.`}
          retry={refresh}
        />
      ) : null}

      <section className="metric-grid" aria-label="Operational summary">
        <MetricCard label="Active incidents" value={unavailable("incidents") ? "—" : String(activeIncidents.length)} detail={`${data.incidents.length} records loaded`} tone={activeIncidents.length ? "warn" : "good"} icon="incidents" href="/incidents" />
        <MetricCard label="Pending approvals" value={unavailable("approvals") ? "—" : String(awaitingApprovals)} detail={awaitingApprovals ? "Operator decision required" : "No action required"} tone={awaitingApprovals ? "warn" : "good"} icon="approvals" href="/approvals" />
        <MetricCard label="Protected services" value={unavailable("service inventory") ? "—" : String(data.services.length)} detail={`${data.clusters.length} managed cluster${data.clusters.length === 1 ? "" : "s"}`} tone="info" icon="reliability" href="/reliability" />
        <MetricCard label="Estimated savings" value={unavailable("FinOps") || savings === undefined ? "—" : new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(savings)} detail={savings === undefined ? "No bounded estimate" : "Monthly opportunity"} tone="neutral" icon="finops" href="/finops" />
      </section>

      <div className="overview-primary-grid">
        <Panel
          eyebrow="Response queue"
          title="Active incidents"
          description="Prioritized by lifecycle state and deterministic risk score."
          action={<Link className="panel-link" to="/incidents">View all <Icon name="arrow" /></Link>}
          className="overview-incidents overview-card"
        >
          {loading ? <LoadingPanel label="Loading incidents" /> : activeIncidents.length ? (
            <>
              <IncidentTable incidents={activeIncidents.slice(0, 6)} services={data.services} />
              {activeIncidents.length > 6 ? <p className="panel-footnote">Showing 6 of {activeIncidents.length} loaded active incidents.</p> : null}
            </>
          ) : <EmptyState title="No open incidents" detail="The incidents API returned no unresolved records." />}
        </Panel>

        <section aria-label="Platform health" className="health-panel">
          <header className="health-panel__header">
            <div><p className="eyebrow">Control plane</p><h2>Platform health</h2></div>
            <StatusBadge label={data.partialFailures.length ? "Partial" : "Operational"} tone={data.partialFailures.length ? "warn" : "good"} dot />
          </header>
          <div className="health-list">
            {healthItems.map((item) => (
              <article className={`health-row health-row--${item.tone}`} key={item.name}>
                <span className={`health-dot health-dot--${item.tone}`} aria-hidden="true" />
                <div><h3>{item.name}</h3><p>{item.detail}</p></div>
                <strong>{item.status}</strong>
                {typeof item.latencyMs === "number" ? <code>{item.latencyMs.toFixed(1)} ms</code> : null}
              </article>
            ))}
          </div>
          <button type="button" className="health-panel__action" onClick={refresh} disabled={loading}>Open live health evidence <Icon name="arrow" /></button>
        </section>
      </div>

      <Panel
        eyebrow="Policy-controlled automation"
        title="Deterministic remediation workflow"
        description="AI may diagnose and summarize. It cannot authorize or execute."
        className="workflow-panel overview-card"
      >
        <ol className="workflow-list">
          {workflow.map((stage, index) => (
            <li key={stage.label}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div><strong>{stage.label}</strong><small>{stage.detail}</small></div>
            </li>
          ))}
        </ol>
      </Panel>

      <div className="overview-secondary-grid">
        <Panel eyebrow="Managed scope" title="Inventory" description="Assets returned by the control-plane API." className="inventory-panel overview-card">
          <div className="inventory-columns">
            <div className="inventory-section">
              <div className="section-heading"><h3>Clusters</h3><Link to="/infrastructure">{data.clusters.length} loaded</Link></div>
              {data.clusters.length ? <ul className="inventory-list">{data.clusters.slice(0, 3).map((item) => <li key={item.id ?? item.name}><div><strong>{item.name ?? "Unnamed cluster"}</strong><small>{item.context_name ?? `${humanize(item.environment)} environment`}</small></div><StatusBadge label={humanize(item.status ?? "inventoried")} tone={stateTone(item.status)} dot /></li>)}</ul> : <p className="quiet-copy">No clusters returned.</p>}
            </div>
            <div className="inventory-section">
              <div className="section-heading"><h3>Services</h3><Link to="/reliability">{data.services.length} loaded</Link></div>
              {data.services.length ? <ul className="inventory-list">{data.services.slice(0, 3).map((service) => <li key={service.id}><div><strong>{service.name}</strong><small>{service.namespace ?? "Namespace not recorded"}</small></div>{service.criticality ? <span className="metadata-label">{humanize(service.criticality)}</span> : null}</li>)}</ul> : <p className="quiet-copy">No services returned.</p>}
            </div>
          </div>
        </Panel>

        <Panel eyebrow="Recent evidence" title="Control-plane activity" description="Newest durable records from the audit window." action={<Link className="panel-link" to="/audit">Audit log <Icon name="arrow" /></Link>} className="overview-card">
          <div className="activity-tabs" aria-label="Activity summary">
            <span><Icon name="deployments" />{deployments.length} deployment events</span>
            <span><Icon name="audit" />{pullRequests.length} pull-request events</span>
            <span><Icon name="security" />{data.securityEvents.length} runtime detections</span>
          </div>
          <ActivityList events={data.audit.slice(0, 5)} empty="No audit activity returned." />
        </Panel>
      </div>

      <section className="safety-boundary" aria-labelledby="safety-title">
        <div className="safety-boundary__icon" aria-hidden="true"><Icon name="shield" /></div>
        <div>
          <h2 id="safety-title">Automation is constrained before execution</h2>
          <p>OPA evaluates every proposal and fails closed. Automatic remediation is limited to registered, reversible actions against explicitly labelled local or staging demo targets.</p>
        </div>
        <div className="safety-boundary__facts">
          <span><Icon name="check" />Allowlisted actions</span>
          <span><Icon name="check" />Human approval gates</span>
          <span><Icon name="check" />Verified outcomes</span>
        </div>
      </section>
    </div>
  );
}

function MetricCard({ label, value, detail, tone, icon, href }: { label: string; value: string; detail: string; tone: Tone; icon: "incidents" | "approvals" | "reliability" | "finops"; href: string }) {
  return (
    <Link className={`metric-card metric-card--${tone}`} to={href}>
      <span className="metric-card__icon"><Icon name={icon} /></span>
      <span className="metric-card__copy"><small>{label}</small><strong>{value}</strong><span>{detail}</span></span>
      <Icon name="arrow" className="metric-card__arrow" />
    </Link>
  );
}

function ActivityList({ events, empty }: { events: AuditEvent[]; empty: string }) {
  return events.length ? (
    <ul className="activity-list">
      {events.map((event, index) => (
        <li key={event.id ?? index}>
          <div><strong>{humanize(event.event_type)}</strong><small>{event.actor ?? "Control plane"}</small></div>
          <StatusBadge label={humanize(event.result)} tone={stateTone(event.result)} />
        </li>
      ))}
    </ul>
  ) : <p className="quiet-copy">{empty}</p>;
}
