import { MemoryRouter } from "react-router-dom";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../app";

function response(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function mockApi(routes: Record<string, unknown>) {
  const fetchMock = vi.fn((input: string | URL | Request) => {
    const path = typeof input === "string" ? input : input instanceof URL ? input.pathname : new URL(input.url).pathname;
    if (!(path in routes)) return response({ error: { message: `No mock for ${path}` } }, 404);
    return response(routes[path]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("CloudWard dashboard", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders overview health and active incidents from the API", async () => {
    mockApi({
      "/api/v1/health": {
        status: "healthy",
        dependencies: {
          postgresql: { status: "healthy" },
          redis: { status: "healthy" },
          opa: { status: "healthy" },
        },
      },
      "/api/v1/incidents": [
        {
          id: "inc-001",
          title: "Unhealthy demo pod",
          service_name: "demo-api",
          environment: "staging",
          state: "VERIFYING",
          risk_score: 18,
          created_at: "2026-08-13T09:00:00Z",
        },
      ],
      "/api/v1/clusters": [
        { id: "cluster-1", name: "cloudward-local", status: "healthy", environment: "local" },
      ],
      "/api/v1/services": [],
    });

    render(<MemoryRouter initialEntries={["/"]}><AppRoutes /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "PostgreSQL" })).toBeInTheDocument();
    expect(screen.getByText("Unhealthy demo pod")).toBeInTheDocument();
    expect(screen.getByText("Deterministic remediation workflow")).toBeInTheDocument();
    expect(screen.getByText("Automation is constrained before execution")).toBeInTheDocument();
  });

  it("never labels missing health data as healthy", async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.pathname : new URL(input.url).pathname;
      if (path === "/api/v1/incidents" || path === "/api/v1/clusters" || path === "/api/v1/services") return response([]);
      return Promise.reject(new Error("control plane offline"));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter initialEntries={["/"]}><AppRoutes /></MemoryRouter>);

    expect(await screen.findByRole("alert")).toHaveTextContent("API health");
    const healthRegion = screen.getByRole("region", { name: "Platform health" });
    expect(within(healthRegion).getAllByText("Unavailable").length).toBeGreaterThan(0);
  });

  it("renders the full deterministic decision record on incident detail", async () => {
    mockApi({
      "/api/v1/incidents/inc-001": {
        id: "inc-001",
        title: "Unhealthy demo pod",
        service_name: "demo-api",
        environment: "staging",
        state: "RESOLVED",
        correlation_id: "corr-001",
        created_at: "2026-08-13T09:00:00Z",
        runbook_id: "reliability.unhealthy-pod",
        runbook_version: 1,
        evidence: [
          { id: "ev-1", evidence_type: "KUBERNETES_STATE", summary: "One pod failed readiness", payload: { ready: 1, desired: 2 } },
          {
            id: "ev-2",
            evidence_type: "HEALTH_CHECK",
            summary: "Post-remediation verification attempt 1",
            payload: { success: true, checks: [{ type: "ready_replicas", expected: 2, actual: 2, passed: true }] },
          },
        ],
        policy_decisions: [
          {
            id: "decision-1",
            allowed: true,
            requires_approval: false,
            reason: "Low-risk reversible staging remediation",
            result: {
              decision: "ALLOW",
              policy_id: "cloudward.remediation.v1",
            },
          },
        ],
      },
      "/api/v1/incidents/inc-001/events": [
        { id: "event-1", event_type: "STATE_CHANGED", from_state: "VERIFYING", to_state: "RESOLVED", actor: "cloudward", timestamp: "2026-08-13T09:01:00Z" },
      ],
      "/api/v1/incidents/inc-001/actions": [
        {
          id: "action-1",
          action_type: "DELETE_UNHEALTHY_POD",
          status: "SUCCEEDED",
          risk_score: 18,
          risk_calculation: { score: 18, classification: "LOW", factors: { blast_radius: 3 } },
        },
      ],
      "/api/v1/incidents/inc-001/audit": [
        { id: "audit-1", event_type: "VERIFICATION_COMPLETED", actor: "cloudward", result: "success", timestamp: "2026-08-13T09:01:00Z" },
      ],
      "/api/v1/services": [],
    });

    render(<MemoryRouter initialEntries={["/incidents/inc-001"]}><AppRoutes /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Unhealthy demo pod" })).toBeInTheDocument();
    for (const heading of ["Timeline", "AI recommendation", "Signal evidence", "Similar incidents", "Risk assessment", "OPA decision", "Runbook", "Allowlisted action", "Verification", "Audit events"]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    for (const factor of ["Environment impact", "Blast radius", "Action destructiveness", "Reversibility", "Diagnostic uncertainty", "Data / security sensitivity"]) {
      expect(screen.getByText(factor)).toBeInTheDocument();
    }
    expect(screen.getByText("Low-risk reversible staging remediation")).toBeInTheDocument();
    expect(screen.getByText("cloudward.remediation.v1")).toBeInTheDocument();
    expect(screen.getByText("Passed")).toBeInTheDocument();
  });

  it("distinguishes an approval-required OPA decision from a denial", async () => {
    mockApi({
      "/api/v1/incidents/inc-approval": {
        id: "inc-approval",
        title: "Approval boundary",
        environment: "staging",
        state: "AWAITING_APPROVAL",
        policy_decisions: [
          {
            allowed: false,
            requires_approval: true,
            reason: "Operator approval is required",
          },
        ],
      },
      "/api/v1/incidents/inc-approval/events": [],
      "/api/v1/incidents/inc-approval/actions": [],
      "/api/v1/incidents/inc-approval/audit": [],
      "/api/v1/services": [],
    });

    render(
      <MemoryRouter initialEntries={["/incidents/inc-approval"]}>
        <AppRoutes />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Approval boundary" })).toBeInTheDocument();
    expect(screen.getByText("Approval required")).toBeInTheDocument();
    expect(screen.queryByText("Denied")).not.toBeInTheDocument();
  });

  it("uses embedded incident history when a supplemental request fails", async () => {
    mockApi({
      "/api/v1/incidents/inc-embedded": {
        id: "inc-embedded",
        title: "Embedded detail",
        environment: "staging",
        state: "VERIFYING",
        events: [{ id: "event-1", event_type: "STATE_CHANGED" }],
        actions: [
          {
            id: "action-1",
            action_type: "DELETE_UNHEALTHY_POD",
            status: "RUNNING",
          },
        ],
        audit_events: [{ id: "audit-1", event_type: "OPA_EVALUATED" }],
      },
      "/api/v1/services": [],
    });

    render(
      <MemoryRouter initialEntries={["/incidents/inc-embedded"]}>
        <AppRoutes />
      </MemoryRouter>,
    );

    expect(await screen.findByText("State Changed")).toBeInTheDocument();
    expect(screen.getByText("DELETE_UNHEALTHY_POD")).toBeInTheDocument();
    expect(screen.getByText("Opa Evaluated")).toBeInTheDocument();
    expect(screen.queryByText("Incident data is incomplete")).not.toBeInTheDocument();
  });

  it("filters the incident register without another request", async () => {
    const fetchMock = mockApi({
      "/api/v1/incidents": [
        { id: "inc-001", title: "Pod unhealthy", service_id: "service-1", environment: "staging", state: "EXECUTING" },
        { id: "inc-002", title: "Database latency", service_name: "payments", environment: "production", state: "RESOLVED" },
      ],
      "/api/v1/services": [{ id: "service-1", name: "demo-api" }],
    });

    render(<MemoryRouter initialEntries={["/incidents"]}><AppRoutes /></MemoryRouter>);
    expect(await screen.findByText("Database latency")).toBeInTheDocument();
    const search = screen.getByRole("searchbox", { name: "Search incidents" });
    fireEvent.change(search, { target: { value: "demo" } });

    await waitFor(() => expect(screen.queryByText("Database latency")).not.toBeInTheDocument());
    expect(screen.getByText("Pod unhealthy")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("redirects protected views to sign in after a 401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ error: { code: "AUTHENTICATION_REQUIRED", message: "Authentication is required" } }),
          { status: 401, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    render(<MemoryRouter initialEntries={["/incidents"]}><AppRoutes /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Continue with GitHub" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Continue with GitHub" })).toHaveAttribute(
      "href",
      "/api/v1/auth/github/login",
    );
  });

  it("counts blocked and escalated incidents as terminal rather than active", async () => {
    mockApi({
      "/api/v1/incidents": [
        { id: "inc-active", title: "Active", environment: "staging", state: "VERIFYING" },
        { id: "inc-blocked", title: "Blocked", environment: "production", state: "BLOCKED" },
        { id: "inc-escalated", title: "Escalated", environment: "production", state: "ESCALATED" },
      ],
      "/api/v1/services": [],
    });

    render(<MemoryRouter initialEntries={["/incidents"]}><AppRoutes /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Incidents" })).toBeInTheDocument();
    const summary = screen.getByRole("region", { name: "Loaded incident summary" });
    expect(within(summary).getByText("Active").nextElementSibling).toHaveTextContent("1");
    expect(within(summary).getByText("Terminal").nextElementSibling).toHaveTextContent("2");
  });
});
