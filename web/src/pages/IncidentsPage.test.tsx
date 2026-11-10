import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockFetch, renderPage } from "../test/utils";
import { IncidentsPage } from "./IncidentsPage";

const REPORTS = [
  {
    id: 2,
    alert_name: "FleetApiDown",
    trigger: "alertmanager",
    status: "done",
    created_at: "2026-11-10T16:04:04",
    finished_at: "2026-11-10T16:05:46",
    category: "service_down",
    confidence: "high",
    summary: "The Fleet API is down.",
  },
  {
    id: 3,
    alert_name: "HighAlertRate",
    trigger: "manual",
    status: "running",
    created_at: "2026-11-10T16:10:00",
    finished_at: null,
    category: null,
    confidence: null,
    summary: null,
  },
];

describe("IncidentsPage", () => {
  it("lists the investigations with links to their reports", async () => {
    mockFetch({ "/agent/reports": { body: REPORTS } });
    renderPage(<IncidentsPage />);

    expect(await screen.findByRole("link", { name: "#2" })).toHaveAttribute("href", "/incidents/2");
    expect(screen.getByText("The Fleet API is down.")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
  });

  it("shows the queued investigation after a 202", async () => {
    mockFetch({
      "/agent/reports": { body: [] },
      "/agent/investigate": { status: 202, body: { alert_name: "FleetApiDown", investigation_id: 7 } },
    });
    renderPage(<IncidentsPage />);

    await userEvent.click(await screen.findByRole("button", { name: "Start investigation" }));
    expect(await screen.findByText(/Investigation #7 queued/)).toBeInTheDocument();
  });

  it("shows the server's reason on 409", async () => {
    mockFetch({
      "/agent/reports": { body: REPORTS },
      "/agent/investigate": { status: 409, body: { detail: "already queued or running" } },
    });
    renderPage(<IncidentsPage />);

    await userEvent.selectOptions(await screen.findByLabelText("Alert"), "HighAlertRate");
    await userEvent.click(screen.getByRole("button", { name: "Start investigation" }));
    expect(await screen.findByText("Not started: already queued or running")).toBeInTheDocument();
    expect(screen.queryByText(/Cannot reach the agent/)).not.toBeInTheDocument();
  });

  it("says when the agent cannot be reached", async () => {
    mockFetch({ "/agent/reports": { status: 503, body: {} } });
    renderPage(<IncidentsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach the agent.");
  });
});
