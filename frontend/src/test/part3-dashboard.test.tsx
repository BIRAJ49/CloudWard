import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../app";

function response(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  }));
}

function mockApi(routes: Record<string, unknown>) {
  vi.stubGlobal("fetch", vi.fn((input: string | URL | Request) => {
    const path = typeof input === "string"
      ? input
      : input instanceof URL
        ? input.pathname
        : new URL(input.url).pathname;
    return path in routes
      ? response(routes[path])
      : response({ error: { code: "NOT_FOUND", message: `No mock for ${path}` } }, 404);
  }));
}

describe("Part 3 operations dashboard", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows AI diagnosis separately from deterministic policy authority", async () => {
    mockApi({
      "/api/v1/auth/me": { user_id: "user-1", login: "operator", role: "Operator" },
      "/api/v1/incidents/inc-ai": {
        id: "inc-ai",
        title: "Bad deployment",
        environment: "staging",
        state: "AWAITING_APPROVAL",
        risk_score: 42,
        policy_decisions: [{ allowed: false, requires_approval: true, reason: "Operator approval required" }],
      },
      "/api/v1/incidents/inc-ai/events": [],
      "/api/v1/incidents/inc-ai/actions": [{ action_type: "REVERT_IMAGE", status: "PROPOSED" }],
      "/api/v1/incidents/inc-ai/audit": [],
      "/api/v1/incidents/inc-ai/diagnosis": {
        incident_id: "inc-ai",
        likely_root_cause: "The latest image increased HTTP failures.",
        confidence: 0.88,
        candidate_runbook: "reliability.bad-deployment:v1",
      },
      "/api/v1/incidents/inc-ai/similar": [],
      "/api/v1/services": [],
    });

    render(<MemoryRouter initialEntries={["/incidents/inc-ai"]}><AppRoutes /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Bad deployment" })).toBeInTheDocument();
    expect(screen.getByText("The latest image increased HTTP failures.")).toBeInTheDocument();
    expect(screen.getByText("Cannot authorize or execute actions")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "OPA decision" })).toBeInTheDocument();
    expect(screen.getByText("Operator approval required")).toBeInTheDocument();
  });

  it("does not fabricate FinOps savings for an empty recommendation set", async () => {
    mockApi({
      "/api/v1/auth/me": { user_id: "viewer-1", login: "viewer", role: "Viewer" },
      "/api/v1/finops/recommendations": [],
    });
    render(<MemoryRouter initialEntries={["/finops"]}><AppRoutes /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "FinOps" })).toBeInTheDocument();
    expect(screen.getByText("No recommendations")).toBeInTheDocument();
    expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
  });

  it("keeps approval actions disabled for Viewer sessions", async () => {
    mockApi({
      "/api/v1/auth/me": { user_id: "viewer-1", login: "viewer", role: "Viewer" },
      "/api/v1/approvals": [{
        id: "approval-1",
        incident_id: "inc-1",
        action_type: "REVERT_IMAGE",
        state: "PENDING",
        risk_score: 44,
        reversible: true,
      }],
    });
    render(<MemoryRouter initialEntries={["/approvals"]}><AppRoutes /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Approvals" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
  });

  it("submits an explicit operator approval comment", async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.pathname : new URL(input.url).pathname;
      if (path === "/api/v1/auth/me") return response({ user_id: "operator-1", login: "operator", role: "Operator" });
      if (path === "/api/v1/approvals") return response([{ id: "approval-1", action_type: "REVERT_IMAGE", status: "PENDING" }]);
      if (path === "/api/v1/approvals/approval-1/approve") return response({ id: "approval-1", action_type: "REVERT_IMAGE", status: "APPROVED", comment: "Evidence reviewed" });
      return response({ error: { message: "Not found" } }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter initialEntries={["/approvals"]}><AppRoutes /></MemoryRouter>);
    fireEvent.change(await screen.findByPlaceholderText("Operator rationale"), { target: { value: "Evidence reviewed" } });
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/approvals/approval-1/approve",
      expect.objectContaining({ body: JSON.stringify({ comment: "Evidence reviewed" }) }),
    ));
  });

  it("renders exactly the nine server-defined Incident Lab scenarios", async () => {
    const scenarios = [
      "Bad Deployment", "CPU Saturation", "Memory Pressure / OOM", "Node / Workload Failure",
      "Suspicious Shell Pattern", "Unexpected Egress", "Privilege-Related Behavior",
      "Overprovisioned Workload", "Wasted Node Capacity",
    ].map((name, index) => ({ id: `scenario-${index + 1}`, name, target_namespace: "cloudward-staging" }));
    mockApi({
      "/api/v1/auth/me": { user_id: "operator-1", login: "operator", role: "Operator" },
      "/api/v1/scenarios": scenarios,
      "/api/v1/executions": [],
    });
    render(<MemoryRouter initialEntries={["/incident-lab"]}><AppRoutes /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Incident Lab" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Start in staging" })).toHaveLength(9);
  });
});
