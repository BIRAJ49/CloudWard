import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { EmptyState, ErrorNotice, LoadingPanel, Panel } from "../components/panel";
import { StatusBadge } from "../components/status-badge";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useControlPlaneEvents } from "../hooks/use-control-plane-events";
import { cloudWardApi } from "../lib/api";
import { displayValue, formatDate, humanize, serviceName, stateTone } from "../lib/format";
import type { ActionRecord, AuditEvent, EvidenceRecord, Incident, IncidentDiagnosis, IncidentEvent, Service, SimilarIncident, Tone } from "../types";

interface DetailState {
  incident?: Incident;
  events: IncidentEvent[];
  actions: ActionRecord[];
  audit: AuditEvent[];
  services: Service[];
  diagnosis?: IncidentDiagnosis;
  similar: SimilarIncident[];
  partialFailures: string[];
}

const emptyDetail: DetailState = { events: [], actions: [], audit: [], services: [], similar: [], partialFailures: [] };

const riskFactors = [
  { key: "environment", label: "Environment impact", maximum: 15 },
  { key: "blast_radius", label: "Blast radius", maximum: 25 },
  { key: "destructiveness", label: "Action destructiveness", maximum: 20 },
  { key: "reversibility", label: "Reversibility", maximum: 15 },
  { key: "uncertainty", label: "Diagnostic uncertainty", maximum: 15 },
  { key: "sensitivity", label: "Data / security sensitivity", maximum: 10 },
] as const;

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.map(asRecord).filter((item): item is Record<string, unknown> => Boolean(item))
    : [];
}

function pickRecord(...values: unknown[]): Record<string, unknown> | undefined {
  for (const value of values) {
    const record = asRecord(value);
    if (record) return record;
  }
  return undefined;
}

function riskTone(score: number | undefined): Tone {
  if (score === undefined) return "neutral";
  if (score <= 30) return "good";
  if (score <= 69) return "warn";
  return "bad";
}

export function IncidentDetailPage() {
  const { incidentId = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  useDocumentTitle(`Incident ${incidentId || "detail"}`);
  const [data, setData] = useState<DetailState>(emptyDetail);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [refreshKey, setRefreshKey] = useState(0);

  const refresh = useCallback(() => {
    setLoading(true);
    setError(undefined);
    setRefreshKey((key) => key + 1);
  }, []);

  useControlPlaneEvents(useCallback((event) => {
    const kind = String(event.type ?? event.event_type ?? "").toLowerCase();
    if (event.incident_id === incidentId || (kind.includes("incident") && !event.incident_id)) {
      setRefreshKey((key) => key + 1);
    }
  }, [incidentId]));

  useEffect(() => {
    if (!incidentId) return;
    const controller = new AbortController();
    Promise.allSettled([
      cloudWardApi.incident(incidentId, controller.signal),
      cloudWardApi.incidentEvents(incidentId, controller.signal),
      cloudWardApi.incidentActions(incidentId, controller.signal),
      cloudWardApi.incidentAudit(incidentId, controller.signal),
      cloudWardApi.services(controller.signal),
      cloudWardApi.incidentDiagnosis(incidentId, controller.signal),
      cloudWardApi.similarIncidents(incidentId, controller.signal),
    ]).then(([incident, events, actions, audit, services, diagnosis, similar]) => {
      if (controller.signal.aborted) return;
      if (incident.status === "rejected") {
        if (incident.reason && typeof incident.reason === "object" && "status" in incident.reason && incident.reason.status === 401) {
          navigate("/login", { replace: true, state: { from: location.pathname } });
          return;
        }
        setError(incident.reason instanceof Error ? incident.reason.message : "Unable to load incident");
        setLoading(false);
        return;
      }

      const failures: string[] = [];
      if (events.status === "rejected" && !Array.isArray(incident.value.events)) failures.push("timeline");
      if (actions.status === "rejected" && !Array.isArray(incident.value.actions)) failures.push("actions");
      if (audit.status === "rejected" && !Array.isArray(incident.value.audit_events)) failures.push("audit trail");
      if (services.status === "rejected") failures.push("service inventory");
      if (diagnosis.status === "rejected" && !(diagnosis.reason && typeof diagnosis.reason === "object" && "status" in diagnosis.reason && diagnosis.reason.status === 404)) failures.push("AI diagnosis");
      if (similar.status === "rejected" && !(similar.reason && typeof similar.reason === "object" && "status" in similar.reason && similar.reason.status === 404)) failures.push("incident memory matches");
      const similarValue = similar.status === "fulfilled" ? similar.value : [];
      const diagnosisValue = diagnosis.status === "fulfilled" ? diagnosis.value ?? undefined : undefined;
      setData({
        incident: incident.value,
        events: events.status === "fulfilled" ? events.value : incident.value.events ?? [],
        actions: actions.status === "fulfilled" ? actions.value : incident.value.actions ?? [],
        audit: audit.status === "fulfilled" ? audit.value : incident.value.audit_events ?? [],
        services: services.status === "fulfilled" ? services.value : [],
        diagnosis: diagnosisValue && diagnosisValue.status !== "NOT_REQUESTED" ? diagnosisValue : undefined,
        similar: Array.isArray(similarValue) ? similarValue : similarValue.items,
        partialFailures: failures,
      });
      setLoading(false);
    });
    return () => controller.abort();
  }, [incidentId, location.pathname, navigate, refreshKey]);

  const incident = data.incident;
  const latestProposal = data.actions.at(-1);
  const latestExecution = incident?.executions?.at(-1);
  const latestAction = latestExecution ? { ...latestProposal, ...latestExecution } : latestProposal;
  const evidence = useMemo(() => {
    if (!incident) return [];
    const items = incident.evidence_snapshots ?? incident.evidence;
    return Array.isArray(items) ? items as EvidenceRecord[] : [];
  }, [incident]);
  const risk = pickRecord(latestAction?.risk_calculation, incident?.risk_calculation);
  const riskScoreValue = latestAction?.risk_score ?? incident?.risk_score ?? risk?.score;
  const riskScore = typeof riskScoreValue === "number" ? riskScoreValue : undefined;
  const latestPolicy = Array.isArray(incident?.policy_decisions) ? incident.policy_decisions.at(-1) : undefined;
  const policy = pickRecord(latestAction?.policy_decision, incident?.policy_decision, latestPolicy);
  const runbook = pickRecord(
    latestAction?.runbook,
    incident?.runbook,
    incident?.selected_runbook,
    incident?.runbook_id ? { id: incident.runbook_id, version: incident.runbook_version } : undefined,
  );
  const action = pickRecord(latestAction, incident?.action, incident?.action_proposal);
  const verificationEvidence = [...evidence].reverse().find((item) => item.summary?.toLowerCase().includes("verification"));
  const verificationAudit = [...data.audit].reverse().find((item) => item.event_type === "VERIFICATION_COMPLETED");
  const verification = pickRecord(
    incident?.verifications?.at(-1),
    latestAction?.verification_result,
    incident?.verification_result,
    incident?.verification,
    verificationEvidence?.payload,
    verificationAudit?.event_metadata,
    verificationAudit?.metadata,
  );
  const alert = pickRecord(
    incident.alerts?.at(-1),
    incident.normalized_alert,
    incident.alert,
    incident.trigger,
    [...evidence].reverse().find((item) => (item.evidence_type ?? item.type)?.toLowerCase().includes("alert"))?.payload,
  );
  const before = pickRecord(
    incident.verifications?.at(-1)?.before_values,
    verification?.before,
    verification?.before_snapshot,
    incident.before_snapshot,
    [...evidence].reverse().find((item) => String(item.phase ?? "").toLowerCase() === "before")?.payload,
  );
  const after = pickRecord(
    incident.verifications?.at(-1)?.after_values,
    verification?.after,
    verification?.after_snapshot,
    incident.after_snapshot,
    [...evidence].reverse().find((item) => String(item.phase ?? "").toLowerCase() === "after")?.payload,
  );
  const diagnosisRootCause = data.diagnosis?.likely_root_cause ?? data.diagnosis?.suspected_root_cause ?? data.diagnosis?.root_cause_summary ?? data.diagnosis?.summary;

  if (loading && !incident) return <div className="page"><LoadingPanel label="Loading incident" /></div>;

  if (error || !incident) {
    return (
      <div className="page">
        <Link className="back-link" to="/incidents">← Incidents</Link>
        <ErrorNotice title="Incident could not be loaded" message={error ?? "The incident does not exist."} retry={refresh} />
      </div>
    );
  }

  const isStopped = ["BLOCKED", "ESCALATED"].includes(incident.state);
  const isTerminal = isStopped || incident.state === "RESOLVED";

  return (
    <div className="page incident-page">
      <div className="breadcrumb"><Link to="/incidents">Incidents</Link><span>/</span><span>{incident.id}</span></div>

      <header className="incident-header">
        <div>
          <div className="incident-header__labels">
            <StatusBadge label={humanize(incident.state)} tone={stateTone(incident.state)} dot />
            <span className="environment-label">{incident.environment ?? "Unknown environment"}</span>
            {incident.severity ? <span className="metadata-label">{humanize(incident.severity)} severity</span> : null}
          </div>
          <h1>{incident.title || humanize(incident.incident_type)}</h1>
          {incident.summary ? <p>{incident.summary}</p> : null}
        </div>
        <button type="button" className="button button--secondary" onClick={refresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh record"}
        </button>
      </header>

      <dl className="incident-facts">
        <div><dt>Service</dt><dd>{serviceName(incident, data.services)}</dd></div>
        <div><dt>Incident type</dt><dd>{humanize(incident.incident_type)}</dd></div>
        <div><dt>Created</dt><dd>{formatDate(incident.created_at)}</dd></div>
        <div><dt>Updated</dt><dd>{formatDate(incident.updated_at)}</dd></div>
        <div><dt>Resolution source</dt><dd>{humanize(incident.resolution_source ?? "Pending")}</dd></div>
        <div><dt>Root-cause summary</dt><dd>{diagnosisRootCause ?? "Not diagnosed"}</dd></div>
        <div><dt>Diagnosis confidence</dt><dd>{displayValue(data.diagnosis?.confidence)}</dd></div>
      </dl>

      {isTerminal ? (
        <div className={`terminal-notice terminal-notice--${stateTone(incident.state)}`}>
          <strong>{humanize(incident.state)} is a terminal state.</strong>
          <span>{incident.state === "RESOLVED" ? "This workflow has completed." : "Automated remediation has stopped; operator review is required."}</span>
        </div>
      ) : null}

      {data.partialFailures.length ? (
        <ErrorNotice
          title="Incident data is incomplete"
          message={`Could not load ${data.partialFailures.join(", ")}. Only returned records are shown.`}
          retry={refresh}
        />
      ) : null}

      <div className="incident-layout">
        <div className="incident-main">
          <Panel title="Alert" description="Normalized trigger payload and stable correlation fields.">
            {alert ? <FactList data={alert} preferred={["alert_name", "fingerprint", "status", "starts_at", "last_received_at", "source", "description"]} /> : <EmptyState title="No normalized alert" detail="The incident was created without an alert payload or the trigger has not been returned." />}
          </Panel>

          <Panel title="Timeline" description={`${data.events.length} loaded state and workflow events.`}>
            {data.events.length ? <Timeline events={data.events} /> : <EmptyState title="No timeline events" detail="The API returned no incident events." />}
          </Panel>

          <Panel title="AI recommendation" description="Supplemental diagnosis only. Risk, OPA, approval, and the typed executor remain authoritative." className="ai-panel">
            {data.diagnosis ? <AIDiagnosis diagnosis={data.diagnosis} /> : <EmptyState title="No AI diagnosis" detail="The deterministic workflow did not escalate to AI, diagnosis is pending, or the provider was unavailable." />}
          </Panel>

          <Panel title="Signal evidence" description="Bounded metrics, logs, traces, and Kubernetes snapshots used by the decision workflow.">
            <SignalEvidence evidence={evidence} />
            {evidence.length ? <details className="all-evidence"><summary>All evidence snapshots ({evidence.length})</summary><EvidenceList evidence={evidence} /></details> : null}
          </Panel>

          <Panel title="Similar incidents" description="Deterministic fingerprint matches from structured incident memory. Historical content is treated as untrusted evidence.">
            {data.similar.length ? <SimilarIncidents incidents={data.similar} /> : <EmptyState title="No similar incidents" detail="No safe historical match met the configured threshold." />}
          </Panel>

          <Panel title="Verification" description="Resolution requires evidence from the configured verification checks.">
            {verification ? <Verification result={verification} before={before} after={after} /> : <EmptyState title="No verification result" detail="Verification has not completed or no result was returned." />}
          </Panel>

          <Panel title="Audit events" description={`${data.audit.length} append-oriented audit records loaded.`}>
            {data.audit.length ? <AuditList events={data.audit} /> : <EmptyState title="No audit events" detail="The API returned no audit records for this incident." />}
          </Panel>
        </div>

        <aside className="decision-rail" aria-label="Risk, policy, and execution decision record">
          <Panel title="Risk assessment" description="Deterministic score from six bounded factors.">
            <RiskSummary score={riskScore} risk={risk} />
          </Panel>

          <Panel title="OPA decision" description="Policy is the final authority and fails closed.">
            {policy ? <PolicySummary policy={policy} /> : <Unavailable label="No policy decision has been recorded." />}
          </Panel>

          <Panel title="Runbook" description="Versioned declarative procedure selected for this incident.">
            {runbook ? <FactList data={runbook} preferred={["id", "version", "action", "verify", "rollback"]} /> : <Unavailable label="No runbook has been selected." />}
          </Panel>

          <Panel title="Allowlisted action" description="Only registered action implementations can execute.">
            {action ? <FactList data={action} preferred={["action_type", "status", "attempt", "parameters", "result", "error_code", "started_at", "completed_at", "created_at"]} /> : <Unavailable label="No action has been proposed." />}
          </Panel>

          <Panel title="Execution context">
            <dl className="fact-list">
              <div><dt>Retry count</dt><dd>{typeof incident.retry_count === "number" ? `${incident.retry_count} of 3` : "Not recorded"}</dd></div>
              <div><dt>Correlation ID</dt><dd><code>{incident.correlation_id ?? "Not recorded"}</code></dd></div>
              <div><dt>Incident ID</dt><dd><code>{incident.id}</code></dd></div>
              <div><dt>Workflow status</dt><dd>{isTerminal ? "Terminal" : "In progress"}</dd></div>
            </dl>
          </Panel>
        </aside>
      </div>
    </div>
  );
}

function Timeline({ events }: { events: IncidentEvent[] }) {
  return (
    <ol className="timeline">
      {events.map((event, index) => (
        <li key={event.id ?? `${event.event_type}-${index}`}>
          <span className={`timeline__marker timeline__marker--${stateTone(event.to_state ?? event.event_type)}`} aria-hidden="true" />
          <div className="timeline__content">
            <div className="timeline__heading"><strong>{humanize(event.event_type ?? "incident_event")}</strong><time>{formatDate(event.timestamp ?? event.created_at)}</time></div>
            {event.from_state || event.to_state ? (
              <p>{event.from_state ? humanize(event.from_state) : "Created"} <span aria-hidden="true">→</span> {humanize(event.to_state ?? undefined)}</p>
            ) : event.message ? <p>{event.message}</p> : event.details ? <p>{displayValue(event.details)}</p> : null}
            <small>Actor: {event.actor ?? "Not recorded"}</small>
          </div>
        </li>
      ))}
    </ol>
  );
}

function EvidenceList({ evidence }: { evidence: EvidenceRecord[] }) {
  return (
    <div className="evidence-list">
      {evidence.map((item, index) => (
        <article key={item.id ?? index} className="evidence-record">
          <header><StatusBadge label={humanize(item.evidence_type ?? item.type)} tone="info" /><time>{formatDate(item.collected_at ?? item.created_at)}</time></header>
          <strong>{item.summary ?? "Evidence snapshot"}</strong>
          {item.data !== undefined || item.payload !== undefined ? <pre>{displayValue(item.data ?? item.payload)}</pre> : null}
        </article>
      ))}
    </div>
  );
}

const signalDefinitions = [
  { key: "metrics", label: "Metrics", providers: ["metric", "prometheus"] },
  { key: "logs", label: "Logs", providers: ["log", "loki"] },
  { key: "traces", label: "Traces", providers: ["trace", "tempo", "span"] },
  { key: "kubernetes", label: "Kubernetes", providers: ["kubernetes", "k8s", "workload", "pod", "deployment"] },
  { key: "deployment", label: "Deployment", providers: ["deployment_evidence", "rollout", "argocd", "image_digest"] },
  { key: "git", label: "Git changes", providers: ["git", "github", "commit", "pull_request", "diff"] },
] as const;

function evidenceDescriptor(item: EvidenceRecord): string {
  const payload = asRecord(item.payload ?? item.data);
  return [item.evidence_type, item.type, payload?.provider, payload?.source, payload?.signal]
    .map((value) => String(value ?? "").toLowerCase())
    .join(" ");
}

function AIDiagnosis({ diagnosis }: { diagnosis: IncidentDiagnosis }) {
  const evidence = Array.isArray(diagnosis.supporting_evidence) ? diagnosis.supporting_evidence : Array.isArray(diagnosis.evidence_refs) ? diagnosis.evidence_refs : [];
  return <div className="ai-diagnosis">
    <div className="ai-boundary-note"><strong>AI recommendation · {humanize(diagnosis.status)}</strong><span>Cannot authorize or execute actions</span></div>
    <dl className="fact-list">
      <div><dt>Likely root cause</dt><dd>{diagnosis.likely_root_cause ?? diagnosis.suspected_root_cause ?? diagnosis.root_cause_summary ?? diagnosis.summary ?? "No concise summary returned"}</dd></div>
      <div><dt>Confidence</dt><dd>{displayValue(diagnosis.confidence)}</dd></div>
      <div><dt>Candidate runbook</dt><dd>{displayValue(diagnosis.candidate_runbook ?? diagnosis.suggested_runbook)}</dd></div>
      <div><dt>Provider / model</dt><dd>{[diagnosis.provider, diagnosis.model ?? diagnosis.model_used].filter(Boolean).join(" / ") || "Not recorded"}</dd></div>
      <div><dt>Fallback used</dt><dd>{displayValue(diagnosis.fallback_used)}</dd></div>
      <div><dt>Candidate actions</dt><dd>{displayValue(diagnosis.action_candidates ?? diagnosis.suggested_actions)}</dd></div>
      <div><dt>Related change</dt><dd>{displayValue(diagnosis.related_change)}</dd></div>
    </dl>
    {diagnosis.explanation ? <p className="ai-explanation">{diagnosis.explanation}</p> : null}
    {evidence.length ? <div className="ai-support"><strong>Supporting evidence</strong><ul>{evidence.slice(0, 8).map((item, index) => <li key={index}>{displayValue(item)}</li>)}</ul></div> : null}
  </div>;
}

function SimilarIncidents({ incidents }: { incidents: SimilarIncident[] }) {
  return <div className="table-scroll"><table className="data-table"><thead><tr><th>Incident</th><th>Type / service</th><th>Similarity</th><th>Successful action</th><th>Resolution</th></tr></thead><tbody>{incidents.map((item, index) => { const id = item.incident_id ?? item.id; const score = item.match_score ?? item.similarity_score ?? item.similarity; const successfulAction = item.successful_action ?? (item.successful ? item.action : undefined); return <tr key={id ?? index}><td>{id ? <Link className="text-link" to={`/incidents/${id}`}>{item.title ?? item.alert_name ?? id}</Link> : item.title ?? "Historical incident"}</td><td><span className="cell-stack"><strong>{humanize(item.incident_type)}</strong><small>{item.service ?? "Service not recorded"}</small></span></td><td>{typeof score === "number" ? `${Math.round(score <= 1 ? score * 100 : score)}%` : "Not scored"}</td><td>{successfulAction ? humanize(successfulAction) : "None recorded"}</td><td><span className="cell-stack"><strong>{humanize(item.resolution_source ?? item.result ?? "Unknown")}</strong><small>{formatDate(item.resolved_at)}</small></span></td></tr>; })}</tbody></table></div>;
}

function SignalEvidence({ evidence }: { evidence: EvidenceRecord[] }) {
  return (
    <div className="signal-evidence-grid">
      {signalDefinitions.map((signal) => {
        const matches = evidence.filter((item) => signal.providers.some((provider) => evidenceDescriptor(item).includes(provider)));
        const latest = matches.at(-1);
        return (
          <article className="signal-evidence-card" key={signal.key}>
            <header><strong>{signal.label}</strong><StatusBadge label={matches.length ? `${matches.length} snapshot${matches.length === 1 ? "" : "s"}` : "Unavailable"} tone={matches.length ? "info" : "neutral"} /></header>
            {latest ? (
              <>
                <p>{latest.summary ?? `${signal.label} evidence snapshot`}</p>
                <time>{formatDate(latest.collected_at ?? latest.created_at)}</time>
                {latest.data !== undefined || latest.payload !== undefined ? <pre>{displayValue(latest.data ?? latest.payload)}</pre> : null}
              </>
            ) : <p className="muted">No bounded {signal.label.toLowerCase()} evidence was returned.</p>}
          </article>
        );
      })}
    </div>
  );
}

function RiskSummary({ score, risk }: { score?: number; risk?: Record<string, unknown> }) {
  const factors = asRecord(risk?.factors);
  const tone = riskTone(score);
  return (
    <div className="risk-summary">
      <div className="risk-score">
        <div><strong>{score ?? "Not scored"}</strong>{score === undefined ? null : <span>/100</span>}</div>
        <StatusBadge
          label={displayValue(risk?.classification ?? risk?.recommended_mode ?? (score === undefined ? "Pending" : score <= 30 ? "Low" : score <= 69 ? "Approval required" : "Blocked"))}
          tone={tone}
        />
      </div>
      <div className="risk-factors">
        {riskFactors.map((factor) => {
          const value = factors?.[factor.key];
          const numericValue = typeof value === "number" ? value : undefined;
          return (
            <div key={factor.key}>
              <span>{factor.label}</span>
              <strong>{numericValue === undefined ? "Not recorded" : `${numericValue} / ${factor.maximum}`}</strong>
              <span className="risk-track" aria-hidden="true"><i style={{ width: `${numericValue === undefined ? 0 : Math.min(100, numericValue / factor.maximum * 100)}%` }} /></span>
            </div>
          );
        })}
      </div>
      <p className="threshold-note">0–30 auto-execute candidate · 31–69 approval required · 70–100 blocked or escalated. OPA can still deny any score.</p>
    </div>
  );
}

function PolicySummary({ policy }: { policy: Record<string, unknown> }) {
  const result = asRecord(policy.result) ?? {};
  const decision = { ...result, ...policy };
  const allowed = decision.allowed;
  const requiresApproval = decision.requires_approval;
  const label = requiresApproval === true ? "Approval required" : allowed === true ? "Allowed" : allowed === false ? "Denied" : "Recorded";
  const tone: Tone = requiresApproval === true ? "warn" : allowed === true ? "good" : allowed === false ? "bad" : "neutral";
  return (
    <div className="policy-summary">
      <StatusBadge label={label} tone={tone} dot />
      <p>{displayValue(decision.reason)}</p>
      <FactList data={decision} preferred={["decision", "policy_id", "decision_id", "policy_version"]} omit={["allowed", "requires_approval", "reason", "result"]} />
    </div>
  );
}

function Verification({ result, before, after }: { result: Record<string, unknown>; before?: Record<string, unknown>; after?: Record<string, unknown> }) {
  const checks = records(result.checks);
  const success = result.success;
  return (
    <div className="verification">
      <div className="verification__summary">
        <StatusBadge label={success === true ? "Passed" : success === false ? "Failed" : "Pending"} tone={success === true ? "good" : success === false ? "bad" : "neutral"} dot={typeof success === "boolean"} />
        <p>{displayValue(result.message ?? result.summary ?? "Verification result returned by the control plane.")}</p>
      </div>
      {checks.length ? (
        <ul className="verification-checks">
          {checks.map((check, index) => (
            <li key={String(check.type ?? index)}>
              <span className={`check-mark check-mark--${check.passed === true ? "good" : "bad"}`} aria-hidden="true">{check.passed === true ? "Pass" : "Fail"}</span>
              <span><strong>{humanize(String(check.type ?? "check"))}</strong><small>Expected {displayValue(check.expected)} · Actual {displayValue(check.actual)}</small></span>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="before-after" aria-label="Before and after evidence">
        <article><span>Before action</span>{before ? <pre>{displayValue(before)}</pre> : <p>Snapshot not returned</p>}</article>
        <article><span>After action</span>{after ? <pre>{displayValue(after)}</pre> : <p>Snapshot not returned</p>}</article>
      </div>
    </div>
  );
}

function AuditList({ events }: { events: AuditEvent[] }) {
  return (
    <ul className="audit-list">
      {events.map((event, index) => (
        <li key={event.id ?? index}>
          <div><strong>{humanize(event.event_type)}</strong><p>{event.action ? humanize(event.action) : displayValue(event.result)}</p></div>
          <span><time>{formatDate(event.timestamp ?? event.created_at)}</time><small>{event.actor ?? "Not recorded"}</small></span>
        </li>
      ))}
    </ul>
  );
}

function FactList({ data, preferred = [], omit = [] }: { data: Record<string, unknown>; preferred?: string[]; omit?: string[] }) {
  const ignored = new Set(["id", "incident_id", "metadata", "risk_calculation", "policy_decision", ...omit]);
  const keys = [...preferred, ...Object.keys(data)]
    .filter((key, index, all) => all.indexOf(key) === index)
    .filter((key) => !ignored.has(key) && data[key] !== undefined)
    .slice(0, 8);
  if (!keys.length) return <Unavailable label="No structured fields were returned." />;
  return (
    <dl className="fact-list">
      {keys.map((key) => <div key={key}><dt>{humanize(key)}</dt><dd>{displayValue(data[key])}</dd></div>)}
    </dl>
  );
}

function Unavailable({ label }: { label: string }) {
  return <p className="quiet-copy">{label}</p>;
}
