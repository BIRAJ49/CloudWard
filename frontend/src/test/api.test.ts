import { afterEach, describe, expect, it, vi } from "vitest";
import { CloudWardApiError, cloudWardApi } from "../lib/api";

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

describe("CloudWard API client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses versioned same-origin paths and propagates a request ID", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    await cloudWardApi.incidents();

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/incidents");
    expect(fetchMock.mock.calls[0][1]).toEqual(
      expect.objectContaining({
        credentials: "include",
        headers: expect.objectContaining({
          Accept: "application/json",
          "X-Request-ID": expect.any(String),
        }),
      }),
    );
  });

  it("maps the structured backend error envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            error: {
              code: "INCIDENT_NOT_FOUND",
              message: "Incident was not found",
              request_id: "req-42",
            },
          },
          { status: 404 },
        ),
      ),
    );

    const error = await cloudWardApi.incident("missing").catch((reason) => reason);

    expect(error).toBeInstanceOf(CloudWardApiError);
    expect(error).toMatchObject({
      message: "Incident was not found",
      status: 404,
      code: "INCIDENT_NOT_FOUND",
      requestId: "req-42",
    });
  });

  it("preserves dependency details from a not-ready health response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            status: "not_ready",
            dependencies: { redis: { status: "down" } },
          },
          { status: 503 },
        ),
      ),
    );

    await expect(cloudWardApi.health()).resolves.toEqual({
      status: "not_ready",
      dependencies: { redis: { status: "down" } },
    });
  });
});
