/**
 * The backend stores UTC timestamps without a time zone ("2026-11-10T16:59:41").
 * Read them as UTC and show them in the viewer's local time.
 */
export function parseUtc(timestamp: string): Date {
  const hasZone = /(Z|[+-]\d{2}:\d{2})$/.test(timestamp);
  return new Date(hasZone ? timestamp : `${timestamp}Z`);
}

export function formatTime(timestamp: string): string {
  return parseUtc(timestamp).toLocaleString();
}

/** "high_temperature" -> "high temperature" */
export function humanize(value: string): string {
  return value.replaceAll("_", " ");
}
