import { humanize } from "../api/format";

const ICONS: Record<string, string> = {
  service_down: "🔴",
  sensor_anomaly: "🌡️",
  alert_storm: "🌪️",
  unknown: "❔",
};

interface Props {
  category: string | null | undefined;
}

/** Root cause category of an agent report; tolerates missing or unexpected values. */
export function CategoryBadge({ category }: Props) {
  if (!category) return <span className="badge badge-neutral">pending</span>;
  const icon = ICONS[category] ?? ICONS.unknown;
  return (
    <span className="badge badge-category">
      <span aria-hidden="true">{icon}</span> {humanize(category)}
    </span>
  );
}
