/** TanStack Query hooks for the incident agent. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getReport, getReports, startInvestigation } from "../api/agent";
import type { ReportSummary } from "../api/agent-types";
import { ApiError } from "../api/client";

/** Poll fast while an investigation is in progress, slowly otherwise. */
export function reportsRefreshInterval(reports: ReportSummary[] | undefined): number {
  const active = reports?.some((r) => r.status === "queued" || r.status === "running");
  return active ? 3_000 : 15_000;
}

export function useReports() {
  return useQuery({
    queryKey: ["reports"],
    queryFn: getReports,
    refetchInterval: (query) => reportsRefreshInterval(query.state.data),
  });
}

export function useReport(id: number) {
  return useQuery({
    queryKey: ["report", id],
    queryFn: () => getReport(id),
    // A report that does not exist will not appear by retrying
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 3,
    // Keep refreshing until the investigation is finished
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 3_000 : false;
    },
  });
}

export function useStartInvestigation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: startInvestigation,
    // The new investigation should show up in the list right away
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["reports"] }),
  });
}
