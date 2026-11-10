/**
 * Fleet API calls. The types come from fleet-api.d.ts, which is generated
 * from the backend's OpenAPI schema (npm run gen:types), so they cannot drift.
 */

import { queryString, request } from "./client";
import type { components } from "./fleet-api";

type Schemas = components["schemas"];
export type Vehicle = Schemas["VehicleOut"];
export type Alert = Schemas["AlertOut"];
export type AlertType = Alert["type"];
export type SensorLog = Schemas["SensorLogOut"];
export type VehicleStatus = Schemas["VehicleStatusOut"];
export type Stats = Schemas["StatsOut"];

/** All browser requests go to /api on this origin (Vite or nginx proxy to the API). */
const BASE = "/api";

export const ALERT_TYPES: AlertType[] = ["high_temperature", "abnormal_status"];

export interface AlertFilters {
  type?: AlertType;
  vehicleId?: number;
  limit?: number;
}

export function getVehicles(): Promise<Vehicle[]> {
  return request<Vehicle[]>(`${BASE}/vehicles`);
}

export function getVehicleStatus(vehicleId: number, limit = 200): Promise<VehicleStatus> {
  return request<VehicleStatus>(`${BASE}/vehicles/${vehicleId}/status${queryString({ limit })}`);
}

export function getAlerts(filters: AlertFilters = {}): Promise<Alert[]> {
  const query = queryString({
    type: filters.type,
    vehicle_id: filters.vehicleId,
    limit: filters.limit,
  });
  return request<Alert[]>(`${BASE}/alerts${query}`);
}

export function getStats(minutes = 15): Promise<Stats> {
  return request<Stats>(`${BASE}/stats${queryString({ minutes })}`);
}
