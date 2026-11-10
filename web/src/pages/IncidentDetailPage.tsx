import { Link, useParams } from "react-router";

import type { RCAReport, ReportDetail } from "../api/agent-types";
import { ApiError } from "../api/client";
import { formatTime, humanize } from "../api/format";
import { CategoryBadge } from "../components/CategoryBadge";
import { DataTable } from "../components/DataTable";
import { ErrorBanner } from "../components/ErrorBanner";
import { Loading } from "../components/Loading";
import { StatusBadge } from "../components/StatusBadge";
import { useReport } from "../hooks/agent";

/** Why the loop, not the model, ended the investigation (stop_reason != "completed") */
const STOP_REASONS: Record<string, string> = {
  max_steps: "The agent used all of its steps before it reached a conclusion.",
  timeout: "The investigation hit its time limit.",
  invalid_output: "The model did not return a valid report.",
  llm_error: "The language model could not be reached.",
};

export function IncidentDetailPage() {
  const { id = "" } = useParams();
  const reportId = Number(id);
  // "/incidents/abc" is not worth a request
  const validId = Number.isInteger(reportId) && reportId > 0;
  const query = useReport(reportId, validId);

  const notFound = query.error instanceof ApiError && query.error.status === 404;
  if (!validId || notFound) {
    return (
      <>
        <h1>Incident not found</h1>
        <p>There is no investigation with ID {id}.</p>
        <Link to="/incidents">Back to the incidents</Link>
      </>
    );
  }

  return (
    <>
      <p>
        <Link to="/incidents">← Incidents</Link>
      </p>
      <h1>Incident #{reportId}</h1>
      {query.isError ? (
        <ErrorBanner error={query.error} service="agent" />
      ) : query.isPending ? (
        <Loading what="report" />
      ) : (
        <IncidentBody incident={query.data} />
      )}
    </>
  );
}

function IncidentBody({ incident }: { incident: ReportDetail }) {
  return (
    <>
      <p>
        Alert <strong>{incident.alert_name}</strong> · <StatusBadge status={incident.status} /> ·
        started {formatTime(incident.created_at)} ({incident.trigger})
      </p>

      {(incident.status === "queued" || incident.status === "running") && (
        <div role="status" className="banner banner-warning">
          The investigation is still {incident.status}. This page updates by itself.
        </div>
      )}

      {incident.status === "failed" && (
        <div role="alert" className="banner banner-error">
          The investigation failed: {incident.error ?? "unknown error"}
        </div>
      )}

      {incident.report && <Report report={incident.report} />}
    </>
  );
}

function Report({ report }: { report: RCAReport }) {
  const stoppedEarly = report.stop_reason !== "completed";
  return (
    <>
      {stoppedEarly && (
        <div role="alert" className="banner banner-warning">
          {STOP_REASONS[report.stop_reason] ?? "The investigation stopped early."} This report was
          written by the agent loop, not by the model, so treat it with care.
        </div>
      )}

      <section aria-labelledby="root-cause-heading">
        <h2 id="root-cause-heading">Root cause</h2>
        <p>{report.summary}</p>
        <p>
          <CategoryBadge category={report.root_cause_category} /> · confidence:{" "}
          <strong>{report.confidence}</strong>
        </p>
        <p className="prewrap">{report.root_cause_explanation}</p>
      </section>

      <section aria-labelledby="evidence-heading">
        <h2 id="evidence-heading">Evidence</h2>
        {report.evidence.length === 0 ? (
          <p className="muted">The report has no evidence.</p>
        ) : (
          <DataTable
            caption="What the agent looked at"
            columns={[
              { header: "Tool", cell: (e) => <code>{e.tool}</code> },
              { header: "Query", cell: (e) => <code>{e.query}</code> },
              { header: "Finding", cell: (e) => e.finding },
            ]}
            rows={report.evidence}
            rowKey={(e) => `${e.tool}|${e.query}|${e.finding}`}
          />
        )}
      </section>

      <section aria-labelledby="actions-heading">
        <h2 id="actions-heading">Suggested actions</h2>
        <p className="muted">Suggestions only: the agent never executes them. A human decides.</p>
        {report.suggested_actions.length === 0 ? (
          <p className="muted">No actions suggested.</p>
        ) : (
          <ol>
            {report.suggested_actions.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ol>
        )}
      </section>

      <section aria-labelledby="run-heading">
        <h2 id="run-heading">Run</h2>
        <dl className="run-facts">
          <dt>Steps used</dt>
          <dd>{report.steps_used}</dd>
          <dt>Duration</dt>
          <dd>{report.duration_seconds.toFixed(1)} s</dd>
          <dt>Stop reason</dt>
          <dd>{humanize(report.stop_reason)}</dd>
        </dl>
      </section>
    </>
  );
}
