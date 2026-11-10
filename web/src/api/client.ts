/**
 * Small wrapper around fetch: JSON in and out, one error type for every failure.
 */

export class ApiError extends Error {
  /** HTTP status code, or 0 if the server could not be reached at all */
  readonly status: number;
  /** The server's explanation (FastAPI's "detail" field) if there is one */
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(status === 0 ? detail : `HTTP ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** FastAPI sends {"detail": "..."} for HTTPException and a list for validation errors. */
function detailFrom(body: unknown): string | undefined {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => (item && typeof item === "object" && "msg" in item ? String(item.msg) : ""))
        .filter(Boolean)
        .join("; ");
    }
  }
  return undefined;
}

export async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");

  let response: Response;
  try {
    response = await fetch(url, { ...init, headers });
  } catch {
    // fetch only rejects when there is no HTTP response (server down, network error)
    throw new ApiError(0, "Network error");
  }

  // A proxy error page or an empty body is not JSON; treat it as "no body"
  const body: unknown = await response.json().catch(() => undefined);
  if (!response.ok) {
    throw new ApiError(response.status, detailFrom(body) ?? response.statusText);
  }
  return body as T;
}

/** Build "?a=1&b=2" from the parameters that are set. */
export function queryString(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
