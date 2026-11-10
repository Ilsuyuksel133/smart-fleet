export function Loading({ what = "data" }: { what?: string }) {
  return (
    <p role="status" className="muted">
      Loading {what}…
    </p>
  );
}
