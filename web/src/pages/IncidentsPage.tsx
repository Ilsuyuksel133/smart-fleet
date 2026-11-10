import { type FormEvent, useState } from "react";
import { Link } from "react-router";

import { INVESTIGATABLE_ALERTS } from "../api/agent";
import type { ReportSummary } from "../api/agent-types";
import { ApiError } from "../api/client";
import { formatTime } from "../api/format";
import { CategoryBadge } from "../components/CategoryBadge";
import { DataTable } from "../components/DataTable";
import { ErrorBanner } from "../components/ErrorBanner";
import { Loading } from "../components/Loading";
import { StatusBadge } from "../components/StatusBadge";
import { useReports, useStartInvestigation } from "../hooks/agent";

function StartInvestigationForm() {
  const [alertName, setAlertName] = useState(INVESTIGATABLE_ALERTS[0] ?? "");
  const start = useStartInvestigation();

  function submit(event: FormEvent) {
    event.preventDefault();
    start.mutate(alertName);
  }

  // 409 means "not started on purpose" (already running), anything else is a real failure
  const conflict = start.error instanceof ApiError && start.error.status === 409;

  return (
    <form onSubmit={submit} className="filters" aria-label="Start an investigation">
      <label>
        Alert
        <select value={alertName} onChange={(event) => setAlertName(event.target.value)}>
          {INVESTIGATABLE_ALERTS.map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
      </label>
      <button type="submit" disabled={start.isPending}>
        Start investigation
      </button>
      {start.isSuccess && (
        <p role="status" className="banner banner-ok">
          Investigation #{start.data.investigation_id} queued. It usually takes about a minute with
          a local model.
        </p>
      )}
      {conflict && (
        <p role="status" className="banner banner-warning">
          Not started: {(start.error as ApiError).detail}
        </p>
      )}
      {start.isError && !conflict && <ErrorBanner error={start.error} service="agent" />}
    </form>
  );
}

export function IncidentsPage() {
  const reports = useReports();

  return (
    <>
      <h1>Incidents</h1>
      <p className="muted">
        Root cause analysis reports written by the AI incident agent. The agent only reads metrics,
        logs and the runbook; every action is up to you.
      </p>

      <section aria-labelledby="start-heading">
        <h2 id="start-heading">Start an investigation</h2>
        <StartInvestigationForm />
      </section>

      <section aria-labelledby="reports-heading">
        <h2 id="reports-heading">Investigations</h2>
        {reports.isError ? (
          <ErrorBanner error={reports.error} service="agent" />
        ) : reports.isPending ? (
          <Loading what="investigations" />
        ) : reports.data.length === 0 ? (
          <p className="muted">No investigations yet. They start automatically when an alert fires.</p>
        ) : (
          <DataTable<ReportSummary>
            caption="Investigations, newest first"
            rows={reports.data}
            rowKey={(report) => report.id}
            columns={[
              {
                header: "#",
                cell: (report) => <Link to={`/incidents/${report.id}`}>#{report.id}</Link>,
              },
              { header: "Alert", cell: (report) => report.alert_name },
              { header: "Status", cell: (report) => <StatusBadge status={report.status} /> },
              { header: "Category", cell: (report) => <CategoryBadge category={report.category} /> },
              { header: "Confidence", cell: (report) => report.confidence ?? "–" },
              { header: "Summary", cell: (report) => report.summary ?? "–" },
              { header: "Started", cell: (report) => formatTime(report.created_at) },
            ]}
          />
        )}
      </section>
    </>
  );
}
