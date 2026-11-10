import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mockFetch, renderPage } from "../test/utils";
import { IncidentDetailPage } from "./IncidentDetailPage";

const REPORT = {
  alert_name: "FleetApiDown",
  summary: "The Fleet API container is down.",
  root_cause_category: "service_down",
  root_cause_explanation: "up{job=\"fleet-api\"} is 0 since 16:04.",
  evidence: [
    { tool: "get_service_health", query: "{}", finding: "fleet-api: down" },
    { tool: "query_loki", query: '{service="api"} |= "error"', finding: "No logs after 16:04" },
  ],
  confidence: "high",
  suggested_actions: ["Runbook FleetApiDown: restart the api container"],
  steps_used: 4,
  duration_seconds: 12.34,
  stop_reason: "completed",
};

function incident(overrides: Record<string, unknown> = {}) {
  return {
    id: 5,
    alert_name: "FleetApiDown",
    trigger: "alertmanager",
    status: "done",
    created_at: "2026-11-10T16:04:04",
    finished_at: "2026-11-10T16:05:46",
    category: "service_down",
    confidence: "high",
    summary: REPORT.summary,
    alert: { name: "FleetApiDown", labels: {}, annotations: {} },
    report: REPORT,
    error: null,
    ...overrides,
  };
}

function renderIncident(id = "5") {
  return renderPage(<IncidentDetailPage />, { route: `/incidents/${id}`, path: "/incidents/:id" });
}

describe("IncidentDetailPage", () => {
  it("shows the root cause, evidence rows and suggested actions", async () => {
    mockFetch({ "/agent/reports/5": { body: incident() } });
    renderIncident();

    expect(await screen.findByRole("heading", { name: "Root cause" })).toBeInTheDocument();
    expect(screen.getByText("The Fleet API container is down.")).toBeInTheDocument();

    const table = screen.getByRole("table", { name: "What the agent looked at" });
    // header row + one row per evidence item
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("No logs after 16:04")).toBeInTheDocument();

    expect(screen.getByRole("listitem")).toHaveTextContent("restart the api container");
    expect(screen.getByText(/never executes them/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("warns when the loop stopped the investigation", async () => {
    mockFetch({
      "/agent/reports/5": {
        body: incident({ report: { ...REPORT, stop_reason: "timeout", confidence: "low" } }),
      },
    });
    renderIncident();

    expect(await screen.findByRole("alert")).toHaveTextContent("hit its time limit");
    expect(screen.getByText("timeout")).toBeInTheDocument();
  });

  it("says when the investigation is still running", async () => {
    mockFetch({
      "/agent/reports/5": { body: incident({ status: "running", report: null, summary: null }) },
    });
    renderIncident();

    expect(await screen.findByText(/still running/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Root cause" })).not.toBeInTheDocument();
  });

  it("shows the error of a failed investigation", async () => {
    mockFetch({
      "/agent/reports/5": {
        body: incident({ status: "failed", report: null, error: "OSError: disk full" }),
      },
    });
    renderIncident();
    expect(await screen.findByRole("alert")).toHaveTextContent("OSError: disk full");
  });

  it("shows 'not found' for an unknown or invalid id", async () => {
    mockFetch({ "/agent/reports/99": { status: 404, body: { detail: "Report not found" } } });
    renderIncident("99");
    expect(await screen.findByRole("heading", { name: "Incident not found" })).toBeInTheDocument();
  });

  it("does not send a request for an invalid id", () => {
    const fetchMock = mockFetch({});
    renderIncident("abc");
    expect(screen.getByRole("heading", { name: "Incident not found" })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("says when the agent cannot be reached", async () => {
    mockFetch({ "/agent/reports/5": { status: 503, body: {} } });
    renderIncident();
    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach the agent.");
  });
});
