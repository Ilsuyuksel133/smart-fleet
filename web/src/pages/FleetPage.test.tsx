import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockFetch, renderPage } from "../test/utils";
import { FleetPage } from "./FleetPage";

const VEHICLES = [
  { id: 1, name: "Truck-1", status: "OK" },
  { id: 2, name: "Truck-2", status: "ERROR" },
  { id: 3, name: "Van-1", status: "OK" },
];

const STATS = {
  window_minutes: 15,
  vehicles_total: 3,
  vehicles_not_ok: 1,
  alerts_by_type: { high_temperature: 4, abnormal_status: 2 },
  per_vehicle: [],
};

function vehicleRows() {
  const table = screen.getByRole("table", { name: /vehicles/i });
  // the first row is the header
  return within(table).getAllByRole("row").slice(1);
}

describe("FleetPage", () => {
  it("shows the statistics and one row per vehicle", async () => {
    mockFetch({ "/api/vehicles": { body: VEHICLES }, "/api/stats": { body: STATS } });
    renderPage(<FleetPage />);

    expect(await screen.findByRole("link", { name: "Truck-1" })).toBeInTheDocument();
    expect(vehicleRows()).toHaveLength(3);
    expect(screen.getByText("Vehicles not OK").nextSibling).toHaveTextContent("1");
    expect(screen.getByText(/high temperature alerts/i).nextSibling).toHaveTextContent("4");
  });

  it("filters by name and by status", async () => {
    mockFetch({ "/api/vehicles": { body: VEHICLES }, "/api/stats": { body: STATS } });
    renderPage(<FleetPage />);
    await screen.findByRole("link", { name: "Truck-1" });

    await userEvent.type(screen.getByLabelText(/search by name/i), "truck");
    expect(vehicleRows()).toHaveLength(2);

    await userEvent.selectOptions(screen.getByLabelText(/status/i), "not_ok");
    const rows = vehicleRows();
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Truck-2");

    await userEvent.type(screen.getByLabelText(/search by name/i), "-9");
    expect(screen.getByText("No vehicles match.")).toBeInTheDocument();
  });

  it("shows an error banner when the API cannot be reached", async () => {
    mockFetch({
      "/api/vehicles": { status: 502, body: {} },
      "/api/stats": { status: 502, body: {} },
    });
    renderPage(<FleetPage />);

    const alerts = await screen.findAllByRole("alert");
    expect(alerts[0]).toHaveTextContent("Cannot reach the API.");
  });
});
