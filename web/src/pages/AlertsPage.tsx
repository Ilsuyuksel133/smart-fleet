import { useState } from "react";
import { Link, useSearchParams } from "react-router";

import { ALERT_TYPES, type Alert, type AlertType } from "../api/fleet";
import { formatTime, humanize } from "../api/format";
import { DataTable } from "../components/DataTable";
import { ErrorBanner } from "../components/ErrorBanner";
import { Loading } from "../components/Loading";
import { useAlerts, useVehicles } from "../hooks/fleet";

export const PAGE_SIZE = 25;
/** Upper limit of the API; enough for a few minutes of simulator alerts */
const FETCH_LIMIT = 1000;

function parseType(value: string | null): AlertType | undefined {
  return ALERT_TYPES.find((type) => type === value);
}

function parseVehicle(value: string | null): number | undefined {
  const id = Number(value);
  return value && Number.isInteger(id) && id > 0 ? id : undefined;
}

export function AlertsPage() {
  // Filters live in the URL (?type=...&vehicle=...), so a filtered view can be shared as a link
  const [searchParams, setSearchParams] = useSearchParams();
  const type = parseType(searchParams.get("type"));
  const vehicleId = parseVehicle(searchParams.get("vehicle"));
  const [page, setPage] = useState(0);

  const alerts = useAlerts({ type, vehicleId, limit: FETCH_LIMIT });
  const vehicles = useVehicles();

  function setFilter(name: "type" | "vehicle", value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(name, value);
    else next.delete(name);
    setSearchParams(next);
    setPage(0); // a new filter starts at the first page
  }

  const rows = alerts.data ?? [];
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const pageRows = rows.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);
  const vehicleName = (id: number) => vehicles.data?.find((v) => v.id === id)?.name ?? `#${id}`;

  return (
    <>
      <h1>Alerts</h1>
      <div className="filters">
        <label>
          Type
          <select value={type ?? ""} onChange={(event) => setFilter("type", event.target.value)}>
            <option value="">All types</option>
            {ALERT_TYPES.map((alertType) => (
              <option key={alertType} value={alertType}>
                {humanize(alertType)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Vehicle
          <select
            value={vehicleId ?? ""}
            onChange={(event) => setFilter("vehicle", event.target.value)}
          >
            <option value="">All vehicles</option>
            {(vehicles.data ?? []).map((vehicle) => (
              <option key={vehicle.id} value={vehicle.id}>
                {vehicle.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {alerts.isError ? (
        <ErrorBanner error={alerts.error} service="API" />
      ) : alerts.isPending ? (
        <Loading what="alerts" />
      ) : rows.length === 0 ? (
        <p className="muted">No alerts match these filters.</p>
      ) : (
        <>
          <DataTable<Alert>
            caption={`${rows.length} alerts, newest first`}
            rows={pageRows}
            rowKey={(alert) => alert.id}
            columns={[
              { header: "Time", cell: (alert) => formatTime(alert.timestamp) },
              {
                header: "Vehicle",
                cell: (alert) => (
                  <Link to={`/vehicles/${alert.vehicle_id}`}>{vehicleName(alert.vehicle_id)}</Link>
                ),
              },
              { header: "Type", cell: (alert) => humanize(alert.type) },
              { header: "Reason", cell: (alert) => alert.reason },
            ]}
          />
          <nav aria-label="Pagination" className="pagination">
            <button
              type="button"
              onClick={() => setPage(currentPage - 1)}
              disabled={currentPage === 0}
            >
              Previous
            </button>
            <span>
              Page {currentPage + 1} of {pageCount}
            </span>
            <button
              type="button"
              onClick={() => setPage(currentPage + 1)}
              disabled={currentPage >= pageCount - 1}
            >
              Next
            </button>
          </nav>
        </>
      )}
    </>
  );
}
