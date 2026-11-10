interface Props {
  status: string;
}

/** Vehicle or investigation status. Unknown values get a neutral style instead of breaking. */
export function StatusBadge({ status }: Props) {
  const tone =
    status === "OK" || status === "done"
      ? "ok"
      : status === "ERROR" || status === "failed"
        ? "bad"
        : status === "queued" || status === "running"
          ? "busy"
          : "neutral";
  return <span className={`badge badge-${tone}`}>{status || "unknown"}</span>;
}
