import { describe, expect, it, vi } from "vitest";

import { mockFetch } from "../test/utils";
import { ApiError, queryString, request } from "./client";

describe("request", () => {
  it("returns the parsed JSON of a 2xx response", async () => {
    mockFetch({ "/api/vehicles": { body: [{ id: 1, name: "Truck-1", status: "OK" }] } });
    await expect(request("/api/vehicles")).resolves.toEqual([
      { id: 1, name: "Truck-1", status: "OK" },
    ]);
  });

  it("throws ApiError with the server's detail on 4xx", async () => {
    mockFetch({ "/agent/investigate": { status: 409, body: { detail: "already queued or running" } } });
    const error = await request("/agent/investigate", { method: "POST", body: "{}" }).catch(
      (e: unknown) => e,
    );
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
    expect((error as ApiError).detail).toBe("already queued or running");
  });

  it("joins FastAPI validation messages", async () => {
    mockFetch({
      "/api/alerts": {
        status: 422,
        body: { detail: [{ msg: "Input should be greater than or equal to 1" }] },
      },
    });
    await expect(request("/api/alerts?limit=0")).rejects.toMatchObject({
      status: 422,
      detail: "Input should be greater than or equal to 1",
    });
  });

  it("uses the status text when a 5xx body is not JSON", async () => {
    mockFetch({
      "/api/stats": async () => new Response("<html>Bad Gateway</html>", { status: 502, statusText: "Bad Gateway" }),
    });
    await expect(request("/api/stats")).rejects.toMatchObject({ status: 502, detail: "Bad Gateway" });
  });

  it("reports status 0 when the server cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(request("/api/vehicles")).rejects.toMatchObject({ status: 0 });
  });

  it("sends JSON headers for a request body", async () => {
    const fetchMock = mockFetch({ "/agent/investigate": { status: 202, body: {} } });
    await request("/agent/investigate", { method: "POST", body: '{"alert_name":"X"}' });
    const headers = fetchMock.mock.calls[0]![1]!.headers as Headers;
    expect(headers.get("Content-Type")).toBe("application/json");
  });
});

describe("queryString", () => {
  it("skips unset parameters", () => {
    expect(queryString({ type: "high_temperature", vehicle_id: undefined, limit: 5 })).toBe(
      "?type=high_temperature&limit=5",
    );
    expect(queryString({ type: undefined })).toBe("");
  });
});
