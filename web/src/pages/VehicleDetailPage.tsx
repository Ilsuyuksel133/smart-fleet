import { Link, useParams } from "react-router";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ApiError } from "../api/client";
import type { Alert } from "../api/fleet";
import { formatTime, humanize, parseUtc } from "../api/format";
import { DataTable } from "../components/DataTable";
import { ErrorBanner } from "../components/ErrorBanner";
import { Loading } from "../components/Loading";
import { StatusBadge } from "../components/StatusBadge";
import { useAlerts, useVehicleStatus, useVehicles } from "../hooks/fleet";

/** Same default as the API's ALERT_TEMP_THRESHOLD; drawn as a reference line */
export const ALERT_TEMP_THRESHOLD = 80;

export function VehicleDetailPage() {
  const { id = "" } = useParams();
  const vehicleId = Number(id);
  // "/vehicles/abc" is not worth a request; such pages are simply "not found"
  const validId = Number.isInteger(vehicleId) && vehicleId > 0;

  const status = useVehicleStatus(vehicleId, validId);
  const alerts = useAlerts({ vehicleId, limit: 50 }, validId);
  const vehicles = useVehicles();
  const vehicle = vehicles.data?.find((v) => v.id === vehicleId);

  const notFound = status.error instanceof ApiError && status.error.status === 404;
  if (!validId || notFound) {
    return (
      <>
        <h1>Vehicle not found</h1>
        <p>There is no vehicle with ID {id}.</p>
        <Link to="/">Back to the fleet</Link>
      </>
    );
  }

  const points = (status.data?.logs ?? []).map((log) => ({
    time: parseUtc(log.timestamp).toLocaleTimeString(),
    temperature: log.temperature,
  }));

  return (
    <>
      <p>
        <Link to="/">← Fleet</Link>
      </p>
      <h1>{vehicle ? vehicle.name : `Vehicle ${vehicleId}`}</h1>
      {vehicle && (
        <p>
          Status: <StatusBadge status={vehicle.status} />
        </p>
      )}

      <section aria-labelledby="chart-heading">
        <h2 id="chart-heading">Temperature history</h2>
        {status.isError ? (
          <ErrorBanner error={status.error} service="API" />
        ) : status.isPending ? (
          <Loading what="readings" />
        ) : points.length === 0 ? (
          <p className="muted">No readings yet.</p>
        ) : (
          <figure
            role="img"
            aria-label={`Temperature of the last ${points.length} readings; alert threshold ${ALERT_TEMP_THRESHOLD} °C`}
            className="chart"
          >
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={points} margin={{ top: 10, right: 20, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="time" minTickGap={40} />
                <YAxis
                  width={70}
                  tickFormatter={(value: number) => `${value} °C`}
                  // Round the range to tens so the ticks are readable (60, 70, 80 ...)
                  domain={[
                    (min: number) => Math.floor(Math.min(min, ALERT_TEMP_THRESHOLD) / 10) * 10,
                    (max: number) => Math.ceil(max / 10) * 10,
                  ]}
                />
                <Tooltip />
                <ReferenceLine
                  y={ALERT_TEMP_THRESHOLD}
                  stroke="#d64545"
                  strokeDasharray="6 4"
                  label={`Alert threshold ${ALERT_TEMP_THRESHOLD} °C`}
                />
                {/* No animation: the data refreshes every few seconds */}
                <Line
                  type="monotone"
                  dataKey="temperature"
                  stroke="#2f6fde"
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </figure>
        )}
      </section>

      <section aria-labelledby="alerts-heading">
        <h2 id="alerts-heading">Alerts of this vehicle</h2>
        {alerts.isError ? (
          <ErrorBanner error={alerts.error} service="API" />
        ) : alerts.isPending ? (
          <Loading what="alerts" />
        ) : alerts.data.length === 0 ? (
          <p className="muted">No alerts for this vehicle.</p>
        ) : (
          <DataTable<Alert>
            caption="Latest alerts of this vehicle"
            rows={alerts.data}
            rowKey={(alert) => alert.id}
            columns={[
              { header: "Time", cell: (alert) => formatTime(alert.timestamp) },
              { header: "Type", cell: (alert) => humanize(alert.type) },
              { header: "Reason", cell: (alert) => alert.reason },
            ]}
          />
        )}
      </section>
    </>
  );
}
