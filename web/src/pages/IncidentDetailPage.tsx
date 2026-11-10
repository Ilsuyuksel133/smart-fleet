import { Link, useParams } from "react-router";

/*
 * TODO (İlsu): implement this page yourself, together with its test
 * (src/pages/IncidentDetailPage.test.tsx).
 *
 * Everything it needs is ready:
 *   - useReport(id) in src/hooks/agent.ts returns a ReportDetail (src/api/agent-types.ts)
 *   - components: CategoryBadge, StatusBadge, ErrorBanner, Loading, DataTable
 *   - formatTime() in src/api/format.ts
 *
 * The page should show:
 *   1. Summary, category (CategoryBadge), confidence and the root cause explanation
 *   2. An evidence table (tool, query, finding); long text must wrap, not be cut off
 *   3. The suggested actions as a list, with a note that the agent never executes them
 *   4. steps_used, duration_seconds and stop_reason, and a warning box when
 *      stop_reason is not "completed" (the loop wrote the report, not the model)
 *   5. While the investigation is queued/running: a "still running" message
 *   6. Loading, error ("Cannot reach the agent") and 404 states
 *
 * The test should cover at least: a timeout report shows the warning, and the
 * evidence rows are rendered (see FleetPage.test.tsx for how to mock fetch).
 */
export function IncidentDetailPage() {
  const { id } = useParams();
  return (
    <>
      <p>
        <Link to="/incidents">← Incidents</Link>
      </p>
      <h1>Incident #{id}</h1>
      <p className="muted">The report view is not implemented yet.</p>
    </>
  );
}
