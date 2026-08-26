export type Tone = "good" | "warn" | "bad" | "neutral" | "info";

export interface Incident {
  id: string;
  title?: string;
  summary?: string;
  incident_type?: string;
  category?: string;
  service?: string | { id?: string; name?: string };
  service_name?: string;
  service_id?: string | null;
  environment?: string;
  state: string;
  severity?: string;
  risk_score?: number | null;
  retry_count?: number;
  runbook_id?: string | null;
  runbook_version?: number | null;
  cluster_id?: string | null;
  resolved_at?: string | null;
  created_at?: string;
  updated_at?: string;
  correlation_id?: string;
  resolution_source?: string | null;
  alert?: Record<string, unknown>;
  normalized_alert?: Record<string, unknown>;
  before_snapshot?: Record<string, unknown>;
  after_snapshot?: Record<string, unknown>;
  evidence?: EvidenceRecord[];
  evidence_snapshots?: EvidenceRecord[];
  risk_calculation?: Record<string, unknown>;
  policy_decision?: Record<string, unknown>;
  runbook?: Record<string, unknown>;
  action?: Record<string, unknown>;
  verification_result?: Record<string, unknown>;
  verifications?: VerificationRecord[];
  alerts?: AlertRecord[];
  executions?: ActionRecord[];
  events?: IncidentEvent[];
  actions?: ActionRecord[];
  policy_decisions?: Array<Record<string, unknown>>;
  audit_events?: AuditEvent[];
  [key: string]: unknown;
}

export interface EvidenceRecord {
  id?: string;
  evidence_type?: string;
  type?: string;
  summary?: string;
  collected_at?: string;
  created_at?: string;
  data?: unknown;
  payload?: unknown;
  [key: string]: unknown;
}

export interface IncidentEvent {
  id?: string;
  event_type?: string;
  from_state?: string | null;
  to_state?: string | null;
  actor?: string;
  message?: string;
  created_at?: string;
  timestamp?: string;
  metadata?: unknown;
  event_metadata?: unknown;
  details?: unknown;
  [key: string]: unknown;
}

export interface ActionRecord {
  id?: string;
  action_type?: string;
  action?: string;
  status?: string;
  risk_score?: number | null;
  risk_calculation?: Record<string, unknown>;
  policy_decision?: Record<string, unknown>;
  runbook?: Record<string, unknown>;
  verification_result?: Record<string, unknown>;
  attempt?: number;
  result?: Record<string, unknown>;
  error_code?: string | null;
  started_at?: string;
  completed_at?: string | null;
  created_at?: string;
  [key: string]: unknown;
}

export interface VerificationRecord {
  id?: string;
  action_execution_id?: string | null;
  attempt?: number;
  success?: boolean;
  checks?: Array<Record<string, unknown>>;
  before_values?: Record<string, unknown>;
  after_values?: Record<string, unknown>;
  started_at?: string;
  completed_at?: string;
  [key: string]: unknown;
}

export interface AlertRecord {
  id?: string;
  source?: string;
  alert_name?: string;
  status?: string;
  severity?: string;
  service?: string;
  environment?: string;
  namespace?: string | null;
  starts_at?: string;
  ends_at?: string | null;
  last_received_at?: string;
  repeat_count?: number;
  [key: string]: unknown;
}

export interface AuditEvent {
  id?: string;
  event_type?: string;
  actor?: string;
  actor_type?: string;
  result?: string;
  action?: string;
  created_at?: string;
  timestamp?: string;
  metadata?: unknown;
  event_metadata?: unknown;
  [key: string]: unknown;
}

export interface Cluster {
  id?: string;
  name?: string;
  environment?: string;
  status?: string;
  connected?: boolean;
  context_name?: string | null;
  labels?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export interface Service {
  id: string;
  cluster_id?: string;
  name: string;
  namespace?: string;
  deployment_name?: string;
  health_url?: string | null;
  criticality?: string;
  labels?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface DependencyCheck {
  status?: string;
  healthy?: boolean;
  message?: string;
  latency_ms?: number;
  [key: string]: unknown;
}

export interface HealthResponse {
  status?: string;
  healthy?: boolean;
  dependencies?: Record<string, DependencyCheck | string | boolean>;
  checks?: Record<string, DependencyCheck | string | boolean>;
  [key: string]: unknown;
}

export interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
    request_id?: string;
  };
  detail?: string | Array<{ msg?: string }>;
}

export interface Principal {
  user_id: string;
  login: string;
  role: "Viewer" | "Operator" | "Admin";
}

export interface SecurityEvent {
  id: string;
  event_type?: string;
  classification?: string;
  severity?: string;
  service?: string;
  service_name?: string;
  namespace?: string;
  pod?: string;
  pod_name?: string;
  workload?: string;
  summary?: string;
  incident_id?: string | null;
  containment_status?: string | null;
  risk_score?: number | null;
  policy_decision?: Record<string, unknown> | string | null;
  occurred_at?: string;
  created_at?: string;
  [key: string]: unknown;
}

export interface IncidentScenario {
  id: string;
  name?: string;
  title?: string;
  description?: string;
  category?: string;
  scenario_type?: string;
  mechanism?: string;
  risk_level?: string;
  timeout_seconds?: number;
  max_duration_seconds?: number;
  duration_seconds?: number;
  max_runtime_seconds?: number;
  target_namespace?: string;
  allowed_namespaces?: string[];
  expected_signals?: string[];
  target?: Record<string, unknown> | string;
  target_selector?: Record<string, string>;
  enabled?: boolean;
  [key: string]: unknown;
}

export interface ScenarioExecution {
  id: string;
  scenario_id: string;
  scenario_name?: string;
  status: string;
  target_namespace?: string;
  target?: Record<string, unknown> | string;
  target_selector?: Record<string, string>;
  incident_id?: string | null;
  requested_by?: string;
  started_at?: string;
  completed_at?: string | null;
  stopped_at?: string | null;
  cleanup_status?: string | null;
  cleanup_completed_at?: string | null;
  details?: Record<string, unknown>;
  error?: string | null;
  failure_reason?: string | null;
  [key: string]: unknown;
}

export interface IncidentDiagnosis {
  id?: string;
  incident_id?: string;
  status?: string;
  source?: string;
  provider?: string;
  model?: string;
  likely_root_cause?: string;
  suspected_root_cause?: string;
  root_cause_summary?: string;
  summary?: string;
  confidence?: number | string;
  supporting_evidence?: unknown[];
  evidence_refs?: unknown[];
  candidate_runbook?: string | Record<string, unknown> | null;
  suggested_runbook?: string | Record<string, unknown> | null;
  suggested_actions?: unknown[];
  action_candidates?: unknown[];
  explanation?: string;
  related_change?: Record<string, unknown> | null;
  model_used?: string;
  fallback_used?: boolean;
  escalation_used?: boolean;
  created_at?: string;
  [key: string]: unknown;
}

export interface SimilarIncident {
  incident_id?: string;
  id?: string;
  title?: string;
  service?: string;
  incident_type?: string;
  similarity?: number;
  similarity_score?: number;
  match_score?: number;
  match_reasons?: string[];
  resolution_source?: string | null;
  successful_action?: string | null;
  action?: string | null;
  successful?: boolean;
  result?: string;
  alert_name?: string;
  runbook_id?: string | null;
  resolved_at?: string | null;
  [key: string]: unknown;
}

export interface FinOpsRecommendation {
  id: string;
  recommendation_type?: string;
  type?: string;
  cluster?: string;
  namespace?: string;
  workload?: string;
  service?: string;
  current?: Record<string, unknown>;
  recommended?: Record<string, unknown>;
  current_config?: Record<string, unknown>;
  recommended_config?: Record<string, unknown>;
  evidence?: Record<string, unknown>;
  estimated_savings?: Record<string, unknown>;
  current_monthly_cost?: number | null;
  recommended_monthly_cost?: number | null;
  estimated_monthly_savings?: number | null;
  savings?: number | null;
  risk_score?: number | null;
  confidence?: number | string | null;
  evidence_window_start?: string;
  evidence_window_end?: string;
  evidence_window?: Record<string, unknown> | string;
  status?: string;
  state?: string;
  github_pr_url?: string | null;
  pr_url?: string | null;
  pr_reference?: string | null;
  explanation?: string;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export interface ApprovalRequest {
  id: string;
  proposal_id?: string;
  action_id?: string;
  incident_id?: string | null;
  action?: string;
  action_type?: string;
  environment?: string;
  risk_score?: number | null;
  blast_radius?: string | number;
  reversible?: boolean;
  requested_by?: string;
  runbook?: string | Record<string, unknown> | null;
  reason?: string;
  status?: string;
  state?: string;
  approver?: string | null;
  decided_by?: string | null;
  decision?: string | null;
  comment?: string | null;
  decision_comment?: string | null;
  target_reference?: string;
  proposal_version?: number;
  expected_state?: Record<string, unknown>;
  invalidated_reason?: string | null;
  expires_at?: string | null;
  created_at?: string;
  decided_at?: string | null;
  [key: string]: unknown;
}

export interface IntegrationStatus {
  name?: string;
  provider?: string;
  configured?: boolean;
  enabled?: boolean;
  status?: string;
  message?: string;
  permissions?: string[];
  [key: string]: unknown;
}

export interface GitOpsDrift {
  environment: string;
  application?: string;
  target_revision?: string;
  observed_revision?: string | null;
  sync_status?: string;
  health_status?: string;
  operation_phase?: string | null;
  reconciled_at?: string | null;
  deployment?: string;
  deployed_images?: string[];
  all_images_digest_pinned?: boolean;
  out_of_sync_resources?: Array<Record<string, string>>;
  classification?: string;
  persistent_drift?: boolean;
  [key: string]: unknown;
}
