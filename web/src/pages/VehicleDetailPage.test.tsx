import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mockFetch, renderPage } from "../test/utils";
import { VehicleDetailPage } from "./VehicleDetailPage";

const PATH = "/vehicles/:id";

describe("VehicleDetailPage", () => {
  it("shows the vehicle, its chart and its alerts", async () => {
    mockFetch({
      "/api/vehicles/1/status": {
        body: {
          vehicle_id: 1,
          logs: [
            { id: 1, vehicle_id: 1, temperature: 70, status: "OK", timestamp: "2026-11-10T16:00:00" },
            { id: 2, vehicle_id: 1, temperature: 92, status: "OK", timestamp: "2026-11-10T16:00:03" },
          ],
        },
      },
      "/api/alerts": {
        body: [
          {
            id: 5,
            vehicle_id: 1,
            type: "high_temperature",
            reason: "High temperature: 92°C",
            timestamp: "2026-11-10T16:00:03",
          },
        ],
      },
      "/api/vehicles": { body: [{ id: 1, name: "Truck-1", status: "OK" }] },
    });
    renderPage(<VehicleDetailPage />, { route: "/vehicles/1", path: PATH });

    expect(await screen.findByRole("heading", { level: 1, name: "Truck-1" })).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: /temperature of the last 2 readings/i })).toBeInTheDocument();
    expect(await screen.findByText("High temperature: 92°C")).toBeInTheDocument();
  });

  it("explains a missing vehicle (404)", async () => {
    mockFetch({
      "/api/vehicles/999/status": { status: 404, body: { detail: "Vehicle not found" } },
      "/api/alerts": { body: [] },
      "/api/vehicles": { body: [] },
    });
    renderPage(<VehicleDetailPage />, { route: "/vehicles/999", path: PATH });
    expect(await screen.findByRole("heading", { name: "Vehicle not found" })).toBeInTheDocument();
  });

  it("does not request an invalid vehicle ID", async () => {
    const fetchMock = mockFetch({ "/api/vehicles": { body: [] } });
    renderPage(<VehicleDetailPage />, { route: "/vehicles/abc", path: PATH });
    expect(await screen.findByRole("heading", { name: "Vehicle not found" })).toBeInTheDocument();
    const urls = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(urls.some((url) => url.includes("/status") || url.includes("/alerts"))).toBe(false);
  });
});
