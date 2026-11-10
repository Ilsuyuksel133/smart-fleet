import { lazy, Suspense } from "react";
import { NavLink, Route, Routes } from "react-router";

import { Loading } from "./components/Loading";
import { AlertsPage } from "./pages/AlertsPage";
import { FleetPage } from "./pages/FleetPage";
import { IncidentDetailPage } from "./pages/IncidentDetailPage";
import { IncidentsPage } from "./pages/IncidentsPage";
import { NotFoundPage } from "./pages/NotFoundPage";

// Only the vehicle page draws a chart; loading it (and the charting library)
// on demand keeps the first page load small
const VehicleDetailPage = lazy(() =>
  import("./pages/VehicleDetailPage").then((module) => ({ default: module.VehicleDetailPage })),
);

// Other tools of the stack; overridable at build time (VITE_GRAFANA_URL, VITE_STREAMLIT_URL)
const GRAFANA_URL = import.meta.env.VITE_GRAFANA_URL ?? "http://localhost:3000";
const STREAMLIT_URL = import.meta.env.VITE_STREAMLIT_URL ?? "http://localhost:8501";

export function App() {
  return (
    <>
      <header className="topbar">
        <span className="brand">🚚 Smart Fleet</span>
        <nav aria-label="Main">
          <NavLink to="/" end>
            Fleet
          </NavLink>
          <NavLink to="/alerts">Alerts</NavLink>
          <NavLink to="/incidents">Incidents</NavLink>
        </nav>
        <nav aria-label="Other tools" className="external">
          <a href={GRAFANA_URL} target="_blank" rel="noreferrer">
            Grafana ↗
          </a>
          <a href={STREAMLIT_URL} target="_blank" rel="noreferrer">
            Streamlit ↗
          </a>
        </nav>
      </header>
      <main>
        <Suspense fallback={<Loading what="page" />}>
          <Routes>
            <Route path="/" element={<FleetPage />} />
            <Route path="/vehicles/:id" element={<VehicleDetailPage />} />
            <Route path="/alerts" element={<AlertsPage />} />
            <Route path="/incidents" element={<IncidentsPage />} />
            <Route path="/incidents/:id" element={<IncidentDetailPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </Suspense>
      </main>
    </>
  );
}
