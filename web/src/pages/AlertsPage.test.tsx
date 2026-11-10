import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockFetch, renderPage } from "../test/utils";
import { AlertsPage, PAGE_SIZE } from "./AlertsPage";

function alert(id: number, type = "high_temperature") {
  return { id, vehicle_id: 1, type, reason: `alert ${id}`, timestamp: "2026-11-10T16:00:00" };
}

describe("AlertsPage", () => {
  it("reads the type filter from the URL and sends it to the API", async () => {
    const fetchMock = mockFetch({
      "/api/alerts": { body: [alert(1, "abnormal_status")] },
      "/api/vehicles": { body: [{ id: 1, name: "Truck-1", status: "OK" }] },
    });
    renderPage(<AlertsPage />, { route: "/alerts?type=abnormal_status", path: "/alerts" });

    expect(await screen.findByText("alert 1")).toBeInTheDocument();
    expect(screen.getByLabelText("Type")).toHaveValue("abnormal_status");
    const alertCalls = fetchMock.mock.calls.map((call) => String(call[0])).filter((u) => u.startsWith("/api/alerts"));
    expect(alertCalls[0]).toContain("type=abnormal_status");
  });

  it("changes the filter and pages through the results", async () => {
    const many = Array.from({ length: PAGE_SIZE + 5 }, (_, i) => alert(100 - i));
    mockFetch({ "/api/alerts": { body: many }, "/api/vehicles": { body: [] } });
    renderPage(<AlertsPage />, { route: "/alerts", path: "/alerts" });

    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(PAGE_SIZE + 1);
    expect(screen.getByText(`Page 1 of 2`)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(5 + 1);

    await userEvent.selectOptions(screen.getByLabelText("Type"), "high_temperature");
    expect(screen.getByLabelText("Type")).toHaveValue("high_temperature");
    expect(await screen.findByText(`Page 1 of 2`)).toBeInTheDocument();
  });
});
