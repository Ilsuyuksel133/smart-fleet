"""The agent's read-only tools, also offered as an MCP server.

The same four tools the agent loop uses (agent/tools.py) are exposed over the
Model Context Protocol, so any MCP client (e.g. Claude Desktop) can query
smart-fleet's metrics, logs, runbook and health with them.

Nothing is duplicated: every MCP tool calls the existing tool through
run_tool(), so the limits, truncation and "errors become text" behaviour are
exactly the same as in the agent. All tools are marked read-only.

Run it over stdio (the transport desktop clients use):

    docker compose exec -T agent python -m agent.mcp_server
"""

import logging

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from agent.config import Settings, get_settings
from agent.tools import build_tools, run_tool

INSTRUCTIONS = (
    "Read-only tools for the smart-fleet vehicle monitoring system: Prometheus metrics, "
    "Loki logs, the operational runbook and a health check. Nothing here can change "
    "the system."
)

# Tells clients that these tools only read data and are safe to call repeatedly
READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)


def create_server(settings: Settings | None = None) -> MCPServer:
    tools = build_tools(settings or get_settings())

    # Typed wrappers: MCP builds each tool's input schema from these signatures
    def query_prometheus(promql: str, minutes: int = 15) -> str:
        return run_tool(tools, "query_prometheus", {"promql": promql, "minutes": minutes})

    def query_loki(logql: str, minutes: int = 15, limit: int = 20) -> str:
        arguments = {"logql": logql, "minutes": minutes, "limit": limit}
        return run_tool(tools, "query_loki", arguments)

    def get_runbook(alert_name: str) -> str:
        return run_tool(tools, "get_runbook", {"alert_name": alert_name})

    def get_service_health() -> str:
        return run_tool(tools, "get_service_health", {})

    server = MCPServer("smart-fleet", instructions=INSTRUCTIONS)
    for function in [query_prometheus, query_loki, get_runbook, get_service_health]:
        server.add_tool(
            function,
            name=function.__name__,
            # The same description the agent's LLM sees
            description=tools[function.__name__].description,
            annotations=READ_ONLY,
        )
    return server


def main() -> None:
    # stdout carries the MCP protocol, so this process must not print anything else.
    # Logs go to stderr; one line per HTTP request would only be noise there.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    create_server().run("stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
