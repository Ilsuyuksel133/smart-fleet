import { ApiError } from "../api/client";

interface Props {
  error: unknown;
  /** Which backend failed, e.g. "API" or "agent" */
  service: "API" | "agent";
}

export function ErrorBanner({ error, service }: Props) {
  const unreachable = !(error instanceof ApiError) || error.status === 0 || error.status >= 500;
  const message = unreachable
    ? `Cannot reach the ${service}.`
    : `The ${service} rejected the request: ${error.detail}`;
  return (
    <div role="alert" className="banner banner-error">
      {message}
    </div>
  );
}
