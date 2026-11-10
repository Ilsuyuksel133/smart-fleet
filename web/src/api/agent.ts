/** Incident agent API calls (proxied under /agent). */

import type { InvestigationStarted, ReportDetail, ReportSummary } from "./agent-types";
import { request } from "./client";

const BASE = "/agent";

export const INVESTIGATABLE_ALERTS = ["FleetApiDown", "VehicleOverheating", "HighAlertRate"];

export function getReports(): Promise<ReportSummary[]> {
  return request<ReportSummary[]>(`${BASE}/reports`);
}

export function getReport(id: number): Promise<ReportDetail> {
  return request<ReportDetail>(`${BASE}/reports/${id}`);
}

export function startInvestigation(alertName: string): Promise<InvestigationStarted> {
  return request<InvestigationStarted>(`${BASE}/investigate`, {
    method: "POST",
    body: JSON.stringify({ alert_name: alertName, labels: {} }),
  });
}
