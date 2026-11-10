import { useState } from "react";
import { Link, useNavigate } from "react-router";

import type { Vehicle } from "../api/fleet";
import { humanize } from "../api/format";
import { DataTable } from "../components/DataTable";
import { ErrorBanner } from "../components/ErrorBanner";
import { Loading } from "../components/Loading";
import { StatCard } from "../components/StatCard";
import { StatusBadge } from "../components/StatusBadge";
import { useStats, useVehicles } from "../hooks/fleet";

type StatusFilter = "all" | "ok" | "not_ok";

const STATS_WINDOW_MINUTES = 15;

export function FleetPage() {
  const vehicles = useVehicles();
  const stats = useStats(STATS_WINDOW_MINUTES);
  const navigate = useNavigate();

  // Controlled inputs: React state is the single source of truth for the filters
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const visible = (vehicles.data ?? []).filter((vehicle) => {
    const matchesName = vehicle.name.toLowerCase().includes(search.trim().toLowerCase());
    const matchesStatus =
      statusFilter === "all" ||
      (statusFilter === "ok" ? vehicle.status === "OK" : vehicle.status !== "OK");
    return matchesName && matchesStatus;
  });

  return (
    <>
      <h1>Fleet</h1>

      <section aria-label="Statistics" className="stat-grid">
        {stats.isError ? (
          <ErrorBanner error={stats.error} service="API" />
        ) : stats.data ? (
          <>
            <StatCard label="Vehicles" value={stats.data.vehicles_total} />
            <StatCard
              label="Vehicles not OK"
              value={stats.data.vehicles_not_ok}
              tone={stats.data.vehicles_not_ok > 0 ? "warning" : "default"}
            />
            {Object.entries(stats.data.alerts_by_type).map(([type, count]) => (
              <StatCard
                key={type}
                label={`${humanize(type)} alerts (${STATS_WINDOW_MINUTES} min)`}
                value={count ?? 0}
              />
            ))}
          </>
        ) : (
          <Loading what="statistics" />
        )}
      </section>

      <section aria-labelledby="vehicles-heading">
        <h2 id="vehicles-heading">Vehicles</h2>
        <div className="filters">
          <label>
            Search by name
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="e.g. Truck"
            />
          </label>
          <label>
            Status
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
            >
              <option value="all">All</option>
              <option value="ok">OK</option>
              <option value="not_ok">Not OK</option>
            </select>
          </label>
        </div>

        {vehicles.isError ? (
          <ErrorBanner error={vehicles.error} service="API" />
        ) : vehicles.isPending ? (
          <Loading what="vehicles" />
        ) : visible.length === 0 ? (
          <p className="muted">No vehicles match.</p>
        ) : (
          <DataTable<Vehicle>
            caption="Vehicles and their latest status"
            rows={visible}
            rowKey={(vehicle) => vehicle.id}
            onRowClick={(vehicle) => navigate(`/vehicles/${vehicle.id}`)}
            columns={[
              { header: "ID", cell: (vehicle) => vehicle.id },
              {
                header: "Name",
                cell: (vehicle) => <Link to={`/vehicles/${vehicle.id}`}>{vehicle.name}</Link>,
              },
              { header: "Status", cell: (vehicle) => <StatusBadge status={vehicle.status} /> },
            ]}
          />
        )}
      </section>
    </>
  );
}
