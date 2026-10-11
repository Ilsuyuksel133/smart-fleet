"""Read-only tools the agent can use to investigate an alert.

Design rules for every tool:
- It only reads data (HTTP GET or reading the runbook file). Nothing here can
  change the system; acting on the findings is left to a human.
- Its output is plain text, kept short (summaries, line limits, truncation),
  because everything a tool returns is sent back to the LLM and a small local
  model has a limited context window.
- It never raises. Timeouts, connection errors and invalid queries are turned
  into a readable "ERROR: ..." message, so the model can see what went wrong
  and try something else instead of the investigation crashing.
"""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from agent.config import Settings


@dataclass
class Tool:
    """A function the LLM may call, plus the description it sees."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema of the arguments
    run: Callable[..., str]

    def definition(self) -> dict[str, Any]:
        """The tool in the Ollama/OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# --- Helpers ---


def truncate(text: str, max_chars: int) -> str:
    """Cut long tool output and say how much was left out."""
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return text[:max_chars] + f"\n[truncated: {omitted} more characters]"


def clamp(value: Any, low: int, high: int, default: int) -> int:
    """Turn an LLM-provided number into a safe integer within [low, high]."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def describe_http_error(error: Exception) -> str:
    """A short, model-readable description of a failed HTTP request."""
    if isinstance(error, httpx.TimeoutException):
        return "ERROR: request timed out"
    if isinstance(error, httpx.HTTPStatusError):
        response = error.response
        # Prometheus returns JSON {"error": "..."}; Loki returns plain text
        try:
            detail = response.json().get("error", response.text)
        except ValueError:
            detail = response.text
        return f"ERROR: HTTP {response.status_code}: {detail.strip()[:300]}"
    if isinstance(error, httpx.HTTPError):
        return f"ERROR: could not connect ({type(error).__name__})"
    return f"ERROR: {type(error).__name__}: {error}"


def format_labels(labels: dict[str, str]) -> str:
    shown = {k: v for k, v in labels.items() if k != "__name__"}
    name = labels.get("__name__", "")
    return name + "{" + ", ".join(f'{k}="{v}"' for k, v in sorted(shown.items())) + "}"


def summarize_series(series: list[dict[str, Any]], max_series: int) -> str:
    """Reduce a time series result to min / max / last value per series.

    Raw data points would waste the model's context; these three numbers are
    usually enough to see whether something is high, low or changing.
    """
    if not series:
        return "No data for this query in the selected time range."
    lines = []
    for item in series[:max_series]:
        values = [float(value) for _, value in item["values"]]
        lines.append(
            f"{format_labels(item['metric'])}: min={min(values):g} max={max(values):g} "
            f"last={values[-1]:g} points={len(values)}"
        )
    if len(series) > max_series:
        lines.append(f"... {len(series) - max_series} more series omitted")
    return "\n".join(lines)


# --- Tools ---


def query_prometheus(settings: Settings, promql: str, minutes: Any = 15) -> str:
    minutes = clamp(minutes, 1, settings.max_query_minutes, default=15)
    end = time.time()
    start = end - minutes * 60
    # About 60 points per series is plenty for a min/max/last summary
    step = max(15, minutes)
    try:
        response = httpx.get(
            f"{settings.prometheus_url}/api/v1/query_range",
            params={"query": promql, "start": start, "end": end, "step": step},
            timeout=settings.tool_timeout_seconds,
        )
        response.raise_for_status()
        result = response.json()["data"]["result"]
    except Exception as error:
        return describe_http_error(error)
    header = f"PromQL: {promql} (last {minutes} min)\n"
    return truncate(
        header + summarize_series(result, settings.max_series), settings.max_tool_output_chars
    )


def query_loki(settings: Settings, logql: str, minutes: Any = 15, limit: Any = 20) -> str:
    minutes = clamp(minutes, 1, settings.max_query_minutes, default=15)
    limit = clamp(limit, 1, settings.max_log_lines, default=20)
    end_ns = time.time_ns()
    start_ns = end_ns - minutes * 60 * 1_000_000_000
    try:
        response = httpx.get(
            f"{settings.loki_url}/loki/api/v1/query_range",
            params={
                "query": logql,
                "start": start_ns,
                "end": end_ns,
                "limit": limit,
                "direction": "backward",  # newest lines first
            },
            timeout=settings.tool_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()["data"]
    except Exception as error:
        return describe_http_error(error)

    header = f"LogQL: {logql} (last {minutes} min)\n"

    # Metric queries such as count_over_time(...) return numbers, not log lines
    if data["resultType"] == "matrix":
        body = summarize_series(data["result"], settings.max_series)
        return truncate(header + body, settings.max_tool_output_chars)

    # Log queries return several streams; merge them and keep the newest lines
    lines = []
    for stream in data["result"]:
        service = stream["stream"].get("service", "?")
        for timestamp_ns, line in stream["values"]:
            lines.append((int(timestamp_ns), service, line))
    if not lines:
        return header + "No log lines matched."
    lines.sort(reverse=True)
    shown = [f"[{service}] {line}" for _, service, line in lines[:limit]]
    body = f"{len(shown)} newest matching lines:\n" + "\n".join(shown)
    return truncate(header + body, settings.max_tool_output_chars)


def get_runbook(settings: Settings, alert_name: str) -> str:
    """Return the runbook section whose heading starts with the alert name."""
    try:
        text = Path(settings.runbook_path).read_text(encoding="utf-8")
    except OSError as error:
        return f"ERROR: runbook not readable ({type(error).__name__})"

    # Sections start with "## <Title>", e.g. "## FleetApiDown (critical)"
    sections = re.split(r"(?m)^## ", text)[1:]
    titles = [section.splitlines()[0].strip() for section in sections]
    wanted = alert_name.strip().lower()
    for title, section in zip(titles, sections):
        if wanted and title.lower().startswith(wanted):
            return truncate("## " + section.strip(), settings.max_tool_output_chars)
    return f"No runbook section for '{alert_name}'. Available sections: " + ", ".join(titles)


def get_service_health(settings: Settings) -> str:
    """Check the API health endpoint and Prometheus' view of its scrape targets."""
    report = []

    try:
        response = httpx.get(f"{settings.api_url}/health", timeout=settings.tool_timeout_seconds)
        report.append(f"API /health: HTTP {response.status_code} {response.text.strip()[:200]}")
    except Exception as error:
        report.append(f"API /health: {describe_http_error(error)}")

    try:
        response = httpx.get(
            f"{settings.prometheus_url}/api/v1/query",
            params={"query": "up"},
            timeout=settings.tool_timeout_seconds,
        )
        response.raise_for_status()
        for item in response.json()["data"]["result"]:
            state = "UP" if item["value"][1] == "1" else "DOWN"
            report.append(f"Prometheus target {format_labels(item['metric'])}: {state}")
    except Exception as error:
        report.append(f"Prometheus 'up' query: {describe_http_error(error)}")

    return "\n".join(report)


# --- Registry ---


def build_tools(settings: Settings) -> dict[str, Tool]:
    """All tools, bound to the given settings, keyed by name."""
    tools = [
        Tool(
            name="query_prometheus",
            description=(
                "Run a PromQL query over the last N minutes and get min/max/last values per "
                "series. Available metrics (and their only labels): "
                "up (labels: job = fleet-api or fleet-agent, instance), "
                "fleet_vehicle_temperature_celsius (gauge: the current temperature, query it "
                "directly without rate; labels: vehicle_id), "
                "fleet_sensor_readings_total (labels: vehicle_id), "
                "fleet_alerts_total (labels: type = high_temperature or abnormal_status), "
                "http_requests_total (labels: method, path, status), "
                "http_request_duration_seconds_bucket (labels: method, path, le). "
                "Examples: fleet_vehicle_temperature_celsius, "
                "sum by (type) (rate(fleet_alerts_total[5m])). "
                "The *_total metrics are counters: they only grow, so use rate(...[5m])."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "promql": {"type": "string", "description": "PromQL expression"},
                    "minutes": {
                        "type": "integer",
                        "description": f"Time range in minutes (1-{settings.max_query_minutes})",
                    },
                },
                "required": ["promql"],
            },
            run=lambda promql, minutes=15: query_prometheus(settings, promql, minutes),
        ),
        Tool(
            name="query_loki",
            description=(
                "Run a LogQL query over the last N minutes. Labels are only 'service' "
                "(api, simulator, agent, prometheus, loki, alloy, grafana, dashboard) and "
                "'level' (info, warning, error); other fields are parsed with '| json', e.g. "
                '{service="api"} | json | status >= 400.'
            ),
            parameters={
                "type": "object",
                "properties": {
                    "logql": {"type": "string", "description": "LogQL query"},
                    "minutes": {
                        "type": "integer",
                        "description": f"Time range in minutes (1-{settings.max_query_minutes})",
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"Maximum log lines (1-{settings.max_log_lines})",
                    },
                },
                "required": ["logql"],
            },
            run=lambda logql, minutes=15, limit=20: query_loki(settings, logql, minutes, limit),
        ),
        Tool(
            name="get_runbook",
            description="Get the runbook section for an alert (symptoms, checks and fixes).",
            parameters={
                "type": "object",
                "properties": {
                    "alert_name": {
                        "type": "string",
                        "description": "Alert name, e.g. FleetApiDown",
                    },
                },
                "required": ["alert_name"],
            },
            run=lambda alert_name: get_runbook(settings, alert_name),
        ),
        Tool(
            name="get_service_health",
            description="Check the API health endpoint and which Prometheus targets are up.",
            parameters={"type": "object", "properties": {}},
            run=lambda: get_service_health(settings),
        ),
    ]
    return {tool.name: tool for tool in tools}


def run_tool(tools: dict[str, Tool], name: str, arguments: dict[str, Any]) -> str:
    """Run a tool requested by the model. Never raises: errors become text."""
    tool = tools.get(name)
    if tool is None:
        return f"ERROR: unknown tool '{name}'. Available tools: {', '.join(tools)}"
    try:
        return tool.run(**(arguments or {}))
    except TypeError as error:
        # The model passed missing or unexpected arguments
        return f"ERROR: invalid arguments for {name}: {error}"
    except Exception as error:
        return f"ERROR: {name} failed: {type(error).__name__}: {error}"
