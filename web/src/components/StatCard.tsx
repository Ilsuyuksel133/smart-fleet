interface Props {
  label: string;
  value: number | string;
  tone?: "default" | "warning";
}

export function StatCard({ label, value, tone = "default" }: Props) {
  return (
    <div className={`stat-card stat-${tone}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  );
}
