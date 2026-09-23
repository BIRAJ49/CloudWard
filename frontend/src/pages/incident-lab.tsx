import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { EmptyState, ErrorNotice, LoadingPanel } from "../components/panel";
import { StatusBadge } from "../components/status-badge";
import { useControlPlaneEvents } from "../hooks/use-control-plane-events";
import { useDocumentTitle } from "../hooks/use-document-title";
import { cloudWardApi } from "../lib/api";
import { displayValue, formatDate, humanize, stateTone } from "../lib/format";
import type { IncidentScenario, Principal, ScenarioExecution, Tone } from "../types";

function scenarioItems(value: IncidentScenario[] | { items: IncidentScenario[] }): IncidentScenario[] {
  return Array.isArray(value) ? value : value.items;
}

function riskTone(value?: string): Tone {
  const risk = value?.toUpperCase();
  if (risk === "HIGH" || risk === "CRITICAL") return "bad";
  if (risk === "MEDIUM") return "warn";
  if (risk === "LOW") return "good";
  return "neutral";
}

export function IncidentLabPage() {
  useDocumentTitle("Incident Lab");
  const navigate = useNavigate();
  const location = useLocation();
  const [scenarios, setScenarios] = useState<IncidentScenario[]>([]);
  const [executions, setExecutions] = useState<ScenarioExecution[]>([]);
  const [principal, setPrincipal] = useState<Principal>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState<string>();
  const [refreshKey, setRefreshKey] = useState(0);

  const refresh = useCallback(() => {
    setLoading(true);
    setError(undefined);
    setRefreshKey((value) => value + 1);
  }, []);

  useControlPlaneEvents(useCallback((event) => {
    const kind = String(event.type ?? event.event_type ?? "").toLowerCase();
    if (kind.includes("execution") || kind.includes("incident_lab")) refresh();
  }, [refresh]));

  useEffect(() => {
    const controller = new AbortController();
    Promise.allSettled([
      cloudWardApi.scenarios(controller.signal),
      cloudWardApi.currentUser(controller.signal),
      cloudWardApi.scenarioExecutions(controller.signal),
    ]).then(([scenarioResponse, user, executionResponse]) => {
      if (controller.signal.aborted) return;
      if (user.status === "rejected") {
        const reason: unknown = user.reason;
        if (reason && typeof reason === "object" && "status" in reason && reason.status === 401) {
          navigate("/login", { replace: true, state: { from: location.pathname } });
          return;
        }
      } else setPrincipal(user.value);
      if (scenarioResponse.status === "fulfilled") setScenarios(scenarioItems(scenarioResponse.value));
      else setError(scenarioResponse.reason instanceof Error ? scenarioResponse.reason.message : "Unable to load incident scenarios");
      if (executionResponse.status === "fulfilled") {
        const value = executionResponse.value;
        setExecutions(Array.isArray(value) ? value : value.items);
      }
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [location.pathname, navigate, refreshKey]);

  async function startScenario(scenario: IncidentScenario) {
    setPending(`start:${scenario.id}`);
    setError(undefined);
    try {
      const execution = await cloudWardApi.startScenario(scenario.id);
      setExecutions((current) => [execution, ...current.filter((item) => item.id !== execution.id)]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to start scenario");
    } finally {
      setPending(undefined);
    }
  }

  async function stopExecution(execution: ScenarioExecution) {
    setPending(`stop:${execution.id}`);
    setError(undefined);
    try {
      const updated = await cloudWardApi.stopScenarioExecution(execution.id);
      setExecutions((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to stop scenario");
    } finally {
      setPending(undefined);
    }
  }

  async function refreshExecution(execution: ScenarioExecution) {
    setPending(`refresh:${execution.id}`);
    setError(undefined);
    try {
      const updated = await cloudWardApi.scenarioExecution(execution.id);
      setExecutions((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to refresh execution");
    } finally {
      setPending(undefined);
    }
  }

  const canLaunch = principal?.role === "Operator" || principal?.role === "Admin";

  return (
    <div className="page incident-lab-console">
      <header className="page-header incident-lab-console__masthead">
        <div>
          <p className="eyebrow">Controlled staging range</p>
          <h1>Incident Lab</h1>
          <p>Exercise the reliability control plane with predefined failures, bounded targets, and a durable cleanup record.</p>
        </div>
        <button type="button" className="button button--secondary" onClick={refresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh range"}
        </button>
      </header>

      <section className="range-clearance" role="note" aria-labelledby="range-clearance-title">
        <div className="range-clearance__stamp"><span>AUTHORIZED</span><strong>STAGING</strong></div>
        <div className="range-clearance__copy"><p className="section-index">Safety clearance</p><h2 id="range-clearance-title">Bounded targets only</h2><p>Targets must carry <code>cloudward.io/demo-target=true</code>. Platform, policy, telemetry, and security namespaces are excluded.</p></div>
        <dl><div><dt>Runtime</dt><dd>Hard timeout</dd></div><div><dt>Cleanup</dt><dd>Required</dd></div><div><dt>Production</dt><dd>Excluded</dd></div></dl>
      </section>

      {principal?.role === "Viewer" ? <ErrorNotice title="Viewer access is read-only" message="An Operator or Admin session is required to launch or stop scenarios." /> : null}
      {error ? <ErrorNotice title="Incident Lab unavailable" message={error} retry={refresh} /> : null}

      <section className="range-catalog" aria-labelledby="range-catalog-title">
        <header className="range-section-header"><div><p className="section-index">01 / Scenario catalog</p><h2 id="range-catalog-title">Nine controlled exercises</h2></div><p>Four reliability · three security · two FinOps</p></header>
        {loading && !scenarios.length ? <LoadingPanel label="Loading scenario catalog" /> : scenarios.length ? (
          <div className="range-catalog__list">
            {scenarios.map((scenario, index) => {
              const duration = scenario.max_runtime_seconds ?? scenario.max_duration_seconds ?? scenario.timeout_seconds;
              const title = scenario.name ?? scenario.title ?? scenario.id;
              return (
                <article className="range-scenario" key={scenario.id}>
                  <span className="range-scenario__number" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                  <header className="range-scenario__header">
                    <div><span className="scenario-code">{scenario.id}</span><h3>{title}</h3><p>{scenario.description ?? "A bounded CloudWard incident scenario."}</p></div>
                    <div className="range-scenario__classification"><StatusBadge label={humanize(scenario.risk_level ?? "bounded")} tone={riskTone(scenario.risk_level)} /><span>{humanize(scenario.mechanism ?? scenario.category ?? scenario.scenario_type)}</span></div>
                  </header>
                  <dl className="range-scenario__facts">
                    <div><dt>Maximum run</dt><dd>{duration ? `${duration} seconds` : "Policy default"}</dd></div>
                    <div><dt>Target</dt><dd>{displayValue(scenario.target ?? scenario.target_selector ?? "Labeled staging workload")}</dd></div>
                  </dl>
                  <div className="range-scenario__signals">
                    <strong>Expected signals</strong>
                    <ul>{(scenario.expected_signals ?? []).map((signal) => <li key={signal}>{humanize(signal)}</li>)}</ul>
                    {!scenario.expected_signals?.length ? <small>Scenario-defined evidence contract</small> : null}
                  </div>
                  <button
                    type="button"
                    className="button button--primary range-scenario__launch"
                    onClick={() => void startScenario(scenario)}
                    disabled={!canLaunch || scenario.enabled === false || pending === `start:${scenario.id}`}
                  >
                    {pending === `start:${scenario.id}` ? "Starting…" : scenario.enabled === false ? "Disabled by policy" : "Start in staging"}
                  </button>
                </article>
              );
            })}
          </div>
        ) : <EmptyState title="No scenarios available" detail="The control plane returned an empty scenario catalog." />}
      </section>

      <section className="range-executions" aria-labelledby="range-executions-title">
        <header className="range-section-header"><div><p className="section-index">02 / Run ledger</p><h2 id="range-executions-title">Execution history</h2></div><p>Durable records · live event stream</p></header>
        <p className="range-executions__rule">Injection alone is never success. Detection, verification, and cleanup must be recorded.</p>
        {executions.length ? (
          <div className="table-scroll range-executions__table">
            <table className="data-table">
              <thead><tr><th>Execution</th><th>Scenario</th><th>Status</th><th>Target</th><th>Incident</th><th>Started</th><th>Cleanup</th><th><span className="visually-hidden">Action</span></th></tr></thead>
              <tbody>{executions.map((execution) => {
                const active = ["PENDING", "STARTING", "RUNNING", "STOPPING"].includes(execution.status.toUpperCase());
                const detailIncidentId = execution.details?.incident_id;
                const incidentId = execution.incident_id ?? (typeof detailIncidentId === "string" ? detailIncidentId : undefined);
                return (
                  <tr key={execution.id}>
                    <td><code>{execution.id}</code></td>
                    <td>{execution.scenario_name ?? execution.scenario_id}</td>
                    <td><StatusBadge label={humanize(execution.status)} tone={stateTone(execution.status)} dot /></td>
                    <td>{displayValue(execution.target_namespace ?? execution.target)}</td>
                    <td>{incidentId ? <Link className="text-link" to={`/incidents/${incidentId}`}>Open incident</Link> : <span className="muted">Pending</span>}</td>
                    <td><time>{formatDate(execution.started_at)}</time></td>
                    <td>{execution.cleanup_completed_at ? "Complete" : humanize(execution.cleanup_status ?? String(execution.details?.current_step ?? "Pending"))}</td>
                    <td><span className="row-actions"><button type="button" className="button button--quiet" onClick={() => void refreshExecution(execution)} disabled={Boolean(pending)}>{pending === `refresh:${execution.id}` ? "Refreshing…" : "Refresh"}</button>{active ? <button type="button" className="button button--quiet" onClick={() => void stopExecution(execution)} disabled={Boolean(pending)}>{pending === `stop:${execution.id}` ? "Stopping…" : "Stop"}</button> : null}</span></td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
        ) : <EmptyState title="No scenario executions" detail="Select a catalog scenario to create a bounded execution." />}
      </section>

      <section className="range-protocol" aria-labelledby="range-protocol-title">
        <header className="range-section-header"><div><p className="section-index">03 / Completion protocol</p><h2 id="range-protocol-title">Scenario lifecycle</h2></div><p>Every stage leaves evidence</p></header>
        <ol className="range-protocol__steps">
          {["Scenario requested", "Safety validation", "Injection started", "Expected signal detected", "Incident created", "Evidence collected", "Diagnosis", "Risk", "OPA", "Remediation / containment", "Verification", "Cleanup", "Completed"].map((stage, index) => <li key={stage}><span>{index + 1}</span><strong>{stage}</strong></li>)}
        </ol>
      </section>
    </div>
  );
}
