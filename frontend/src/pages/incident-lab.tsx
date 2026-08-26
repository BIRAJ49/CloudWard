import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { EmptyState, ErrorNotice, LoadingPanel, Panel } from "../components/panel";
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
    <div className="page incident-lab-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Local reliability validation</p>
          <h1>Incident Lab</h1>
          <p>Run bounded failure scenarios against labeled staging targets and watch CloudWard collect evidence, remediate, and verify recovery.</p>
        </div>
        <button type="button" className="button button--secondary" onClick={refresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh catalog"}
        </button>
      </header>

      <div className="lab-boundary" role="note">
        <div><strong>Staging only</strong><span>Targets must carry <code>cloudward.io/demo-target=true</code>.</span></div>
        <div><strong>Hard timeouts</strong><span>Every scenario has bounded duration and cleanup.</span></div>
        <div><strong>Protected namespaces</strong><span>Platform, policy, telemetry, and security namespaces are excluded.</span></div>
      </div>

      {principal?.role === "Viewer" ? <ErrorNotice title="Viewer access is read-only" message="An Operator or Admin session is required to launch or stop scenarios." /> : null}
      {error ? <ErrorNotice title="Incident Lab unavailable" message={error} retry={refresh} /> : null}

      <Panel title="Scenario catalog" description="Exactly four reliability, three security, and two FinOps demonstrations use safe, predefined targets and expected signals.">
        {loading && !scenarios.length ? <LoadingPanel label="Loading scenario catalog" /> : scenarios.length ? (
          <div className="scenario-grid">
            {scenarios.map((scenario) => {
              const duration = scenario.max_runtime_seconds ?? scenario.max_duration_seconds ?? scenario.timeout_seconds;
              const title = scenario.name ?? scenario.title ?? scenario.id;
              return (
                <article className="scenario-card" key={scenario.id}>
                  <header>
                    <div><span className="scenario-code">{scenario.id}</span><h3>{title}</h3></div>
                    <StatusBadge label={humanize(scenario.risk_level ?? "bounded")} tone={riskTone(scenario.risk_level)} />
                  </header>
                  <p>{scenario.description ?? "A bounded CloudWard incident scenario."}</p>
                  <dl>
                    <div><dt>Type</dt><dd>{humanize(scenario.mechanism ?? scenario.category ?? scenario.scenario_type)}</dd></div>
                    <div><dt>Maximum run</dt><dd>{duration ? `${duration} seconds` : "Policy default"}</dd></div>
                    <div><dt>Target</dt><dd>{displayValue(scenario.target ?? scenario.target_selector ?? "Labeled staging workload")}</dd></div>
                  </dl>
                  <div className="expected-signals">
                    <span>Expected signals</span>
                    <ul>{(scenario.expected_signals ?? []).map((signal) => <li key={signal}>{humanize(signal)}</li>)}</ul>
                    {!scenario.expected_signals?.length ? <small>Scenario-defined evidence contract</small> : null}
                  </div>
                  <button
                    type="button"
                    className="button button--primary button--full"
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
      </Panel>

      <Panel title="Execution history" description="Durable executions update through the authenticated event stream. Injection alone is never shown as success.">
        {executions.length ? (
          <div className="table-scroll">
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
      </Panel>

      <Panel title="Scenario lifecycle" description="Every execution must progress through detection, decision, verification, and cleanup before completion.">
        <ol className="lab-lifecycle">
          {["Scenario requested", "Safety validation", "Injection started", "Expected signal detected", "Incident created", "Evidence collected", "Diagnosis", "Risk", "OPA", "Remediation / containment", "Verification", "Cleanup", "Completed"].map((stage, index) => <li key={stage}><span>{index + 1}</span><strong>{stage}</strong></li>)}
        </ol>
      </Panel>
    </div>
  );
}
