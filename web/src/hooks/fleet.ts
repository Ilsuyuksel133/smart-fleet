/**
 * TanStack Query hooks for the fleet API.
 *
 * Why not fetch in useEffect: TanStack Query caches responses (switching pages
 * shows data at once), retries failed requests, refreshes on an interval and
 * exposes loading/error states, all without hand-written effect code.
 */

import { useQuery } from "@tanstack/react-query";

import { ApiError } from "../api/client";
import {
  type AlertFilters,
  getAlerts,
  getStats,
  getVehicleStatus,
  getVehicles,
} from "../api/fleet";

/** The simulator sends a reading every 3 s; refresh fleet data every 5 s. */
export const FLEET_REFRESH_MS = 5_000;

export function useVehicles() {
  return useQuery({
    queryKey: ["vehicles"],
    queryFn: getVehicles,
    refetchInterval: FLEET_REFRESH_MS,
  });
}

export function useStats(minutes = 15) {
  return useQuery({
    queryKey: ["stats", minutes],
    queryFn: () => getStats(minutes),
    refetchInterval: FLEET_REFRESH_MS,
  });
}

export function useAlerts(filters: AlertFilters = {}, enabled = true) {
  return useQuery({
    // The filters are part of the key, so every filter combination is cached separately
    queryKey: ["alerts", filters],
    queryFn: () => getAlerts(filters),
    refetchInterval: FLEET_REFRESH_MS,
    enabled,
  });
}

export function useVehicleStatus(vehicleId: number, enabled = true) {
  return useQuery({
    queryKey: ["vehicle-status", vehicleId],
    queryFn: () => getVehicleStatus(vehicleId),
    refetchInterval: FLEET_REFRESH_MS,
    enabled,
    // A missing vehicle will not appear by retrying
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 3,
  });
}
