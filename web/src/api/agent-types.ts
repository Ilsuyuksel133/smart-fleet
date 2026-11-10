/**
 * Types of the incident agent's API, written by hand.
 * They mirror agent/report.py (RCAReport, Alert) and agent/storage.py (to_dict).
 */

export type InvestigationStatus = "queued" | "running" | "done" | "failed";
export type RootCauseCategory = "service_down" | "sensor_anomaly" | "alert_storm" | "unknown";
export type Confidence = "low" | "medium" | "high";
export type StopReason = "completed" | "max_steps" | "timeout" | "invalid_output" | "llm_error";

export interface Evidence {
  tool: string;
  query: string;
  finding: string;
}

export interface RCAReport {
  alert_name: string;
  summary: string;
  root_cause_category: RootCauseCategory;
  root_cause_explanation: string;
  evidence: Evidence[];
  confidence: Confidence;
  suggested_actions: string[];
  steps_used: number;
  duration_seconds: number;
  stop_reason: StopReason;
}

/** One row of GET /reports */
export interface ReportSummary {
  id: number;
  alert_name: string;
  trigger: "alertmanager" | "manual";
  status: InvestigationStatus;
  created_at: string;
  finished_at: string | null;
  category: RootCauseCategory | null;
  confidence: Confidence | null;
  summary: string | null;
}

/** GET /reports/{id} */
export interface ReportDetail extends ReportSummary {
  alert: { name: string; labels: Record<string, string>; annotations: Record<string, string> };
  report: RCAReport | null;
  error: string | null;
}

/** 202 response of POST /investigate */
export interface InvestigationStarted {
  alert_name: string;
  investigation_id: number;
}
