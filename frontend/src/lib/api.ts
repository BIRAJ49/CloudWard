import type {
  ActionRecord,
  AuditEvent,
  Cluster,
  FinOpsRecommendation,
  GitOpsDrift,
  HealthResponse,
  Incident,
  IncidentDiagnosis,
  IncidentEvent,
  IncidentScenario,
  IntegrationStatus,
  ApprovalRequest,
  Principal,
  ScenarioExecution,
  SecurityEvent,
  Service,
  SimilarIncident,
} from "../types";

const configuredBase = import.meta.env.VITE_API_BASE_URL?.trim();
export const API_BASE_URL = (configuredBase || "/api/v1").replace(/\/$/, "");

export class CloudWardApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;

  constructor(
    message: string,
    options: { status: number; code?: string; requestId?: string },
  ) {
    super(message);
    this.name = "CloudWardApiError";
    this.status = options.status;
    this.code = options.code ?? "API_REQUEST_FAILED";
    this.requestId = options.requestId;
  }
}

function newRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `cw-ui-${Date.now().toString(36)}`;
}

async function request<T>(
  path: string,
  signal?: AbortSignal,
  init: RequestInit = {},
  acceptedStatuses: number[] = [],
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      "X-Request-ID": newRequestId(),
      ...init.headers,
    },
    signal,
  });

  if (!response.ok && !acceptedStatuses.includes(response.status)) {
    let body: {
      error?: { code?: string; message?: string; request_id?: string };
      detail?: string | Array<{ msg?: string }>;
    } = {};
    try {
      body = (await response.json()) as typeof body;
    } catch {
      // A proxy may return an HTML error. Keep the client-facing message safe.
    }
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item) => item.msg).filter(Boolean).join(", ")
      : body.detail;
    throw new CloudWardApiError(
      body.error?.message || detail || `Request failed with status ${response.status}`,
      {
        status: response.status,
        code: body.error?.code,
        requestId:
          body.error?.request_id ?? response.headers.get("X-Request-ID") ?? undefined,
      },
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const cloudWardApi = {
  health: (signal?: AbortSignal) => request<HealthResponse>("/health", signal, {}, [503]),
  incidents: (signal?: AbortSignal) => request<Incident[]>("/incidents", signal),
  incident: (id: string, signal?: AbortSignal) =>
    request<Incident>(`/incidents/${encodeURIComponent(id)}`, signal),
  incidentEvents: (id: string, signal?: AbortSignal) =>
    request<IncidentEvent[]>(
      `/incidents/${encodeURIComponent(id)}/events`,
      signal,
    ),
  incidentActions: (id: string, signal?: AbortSignal) =>
    request<ActionRecord[]>(
      `/incidents/${encodeURIComponent(id)}/actions`,
      signal,
    ),
  incidentAudit: (id: string, signal?: AbortSignal) =>
    request<AuditEvent[]>(
      `/incidents/${encodeURIComponent(id)}/audit`,
      signal,
    ),
  incidentDiagnosis: (id: string, signal?: AbortSignal) =>
    request<IncidentDiagnosis | null>(
      `/incidents/${encodeURIComponent(id)}/diagnosis`,
      signal,
    ),
  similarIncidents: (id: string, signal?: AbortSignal) =>
    request<SimilarIncident[] | { items: SimilarIncident[] }>(
      `/incidents/${encodeURIComponent(id)}/similar`,
      signal,
    ),
  clusters: (signal?: AbortSignal) => request<Cluster[]>("/clusters", signal),
  services: (signal?: AbortSignal) => request<Service[]>("/services", signal),
  gitopsDrift: (environment: "staging" | "production", signal?: AbortSignal) =>
    request<GitOpsDrift>(`/gitops/drift/${environment}`, signal),
  securityEvents: (signal?: AbortSignal) =>
    request<SecurityEvent[] | { items: SecurityEvent[] }>("/security/events", signal),
  finopsRecommendations: (signal?: AbortSignal) =>
    request<FinOpsRecommendation[] | { items: FinOpsRecommendation[] }>(
      "/finops/recommendations",
      signal,
    ),
  approvals: (signal?: AbortSignal) =>
    request<ApprovalRequest[] | { items: ApprovalRequest[] }>("/approvals", signal),
  approve: (approvalId: string, comment: string, signal?: AbortSignal) =>
    request<ApprovalRequest>(`/approvals/${encodeURIComponent(approvalId)}/approve`, signal, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ comment }),
    }),
  reject: (approvalId: string, comment: string, signal?: AbortSignal) =>
    request<ApprovalRequest>(`/approvals/${encodeURIComponent(approvalId)}/reject`, signal, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ comment }),
    }),
  audit: (signal?: AbortSignal) => request<AuditEvent[] | { items: AuditEvent[] }>("/audit", signal),
  githubIntegration: (signal?: AbortSignal) =>
    request<IntegrationStatus>("/integrations/github", signal),
  teamsIntegration: (signal?: AbortSignal) =>
    request<IntegrationStatus>("/integrations/teams", signal),
  applyContainment: (eventId: string, signal?: AbortSignal) =>
    request<Record<string, unknown>>(
      `/security/events/${encodeURIComponent(eventId)}/containment/apply`,
      signal,
      { method: "POST" },
    ),
  removeContainment: (eventId: string, signal?: AbortSignal) =>
    request<Record<string, unknown>>(
      `/security/events/${encodeURIComponent(eventId)}/containment/remove`,
      signal,
      { method: "POST" },
    ),
  scenarios: (signal?: AbortSignal) =>
    request<IncidentScenario[] | { items: IncidentScenario[] }>("/scenarios", signal),
  startScenario: (scenarioId: string, signal?: AbortSignal) =>
    request<ScenarioExecution>(
      `/scenarios/${encodeURIComponent(scenarioId)}/start`,
      signal,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
    ),
  scenarioExecution: (executionId: string, signal?: AbortSignal) =>
    request<ScenarioExecution>(`/executions/${encodeURIComponent(executionId)}`, signal),
  scenarioExecutions: (signal?: AbortSignal) =>
    request<ScenarioExecution[] | { items: ScenarioExecution[] }>("/executions", signal),
  stopScenarioExecution: (executionId: string, signal?: AbortSignal) =>
    request<ScenarioExecution>(
      `/executions/${encodeURIComponent(executionId)}/stop`,
      signal,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
    ),
  currentUser: (signal?: AbortSignal) => request<Principal>("/auth/me", signal),
  developmentLogin: (
    login: string,
    role: Principal["role"],
    signal?: AbortSignal,
  ) =>
    request<Principal>("/auth/dev", signal, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ login, role }),
    }),
  logout: (signal?: AbortSignal) =>
    request<void>("/auth/logout", signal, { method: "POST" }),
};
