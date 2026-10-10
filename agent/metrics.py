"""Prometheus metrics of the agent itself (scraped from /metrics)."""

from prometheus_client import Counter, Histogram

INVESTIGATIONS = Counter(
    "agent_investigations_total",
    "Finished investigations by root cause category",
    ["category"],
)
INVESTIGATION_DURATION = Histogram(
    "agent_investigation_duration_seconds",
    "Duration of an investigation in seconds",
    # A local model needs tens of seconds per investigation
    buckets=(5, 15, 30, 60, 90, 120, 180, 300, 600),
)
STEPS_PER_INVESTIGATION = Histogram(
    "agent_steps_per_investigation",
    "Number of LLM calls (steps) per investigation",
    buckets=(1, 2, 3, 4, 5, 6, 8, 10, 12),
)
TOOL_CALLS = Counter(
    "agent_tool_calls_total",
    "Tool calls made by the agent",
    ["tool"],
)


def initialize(tool_names: list[str]) -> None:
    """Create every known label combination with value 0 at startup.

    A counter series that appears for the first time already at 1 is invisible
    to increase()/rate(), which then report 0 for the first event. Starting all
    series at 0 makes the first investigation show up in Grafana.
    """
    for category in ("service_down", "sensor_anomaly", "alert_storm", "unknown"):
        INVESTIGATIONS.labels(category)
    for tool in tool_names:
        TOOL_CALLS.labels(tool)
