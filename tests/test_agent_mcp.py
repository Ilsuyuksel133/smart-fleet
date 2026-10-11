import httpx
import pytest
import respx
from mcp import Client

from agent.config import Settings
from agent.mcp_server import create_server

PROM = "http://prom.test"
API = "http://api.test"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def server(tmp_path):
    runbook = tmp_path / "RUNBOOK.md"
    runbook.write_text("## FleetApiDown (critical)\n\nThe API is down.\n", encoding="utf-8")
    return create_server(Settings(prometheus_url=PROM, api_url=API, runbook_path=runbook))


@pytest.mark.anyio
async def test_lists_the_four_read_only_tools(server):
    async with Client(server, raise_exceptions=True) as client:
        result = await client.list_tools()

    tools = {tool.name: tool for tool in result.tools}
    assert set(tools) == {"query_prometheus", "query_loki", "get_runbook", "get_service_health"}
    for tool in tools.values():
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
    # Same descriptions as the agent's tools, and schemas built from the signatures
    assert "fleet_vehicle_temperature_celsius" in tools["query_prometheus"].description
    schema = tools["query_loki"].input_schema
    assert set(schema["properties"]) == {"logql", "minutes", "limit"}
    assert schema["required"] == ["logql"]


@pytest.mark.anyio
async def test_get_runbook_through_mcp(server):
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("get_runbook", {"alert_name": "FleetApiDown"})
    assert result.content[0].text.startswith("## FleetApiDown (critical)")


@pytest.mark.anyio
@respx.mock
async def test_query_prometheus_through_mcp(server):
    respx.get(f"{PROM}/api/v1/query_range").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "resultType": "matrix",
                    "result": [
                        {"metric": {"__name__": "up", "job": "fleet-api"}, "values": [[1, "1"]]}
                    ],
                }
            },
        )
    )
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("query_prometheus", {"promql": "up", "minutes": 5})
    assert 'up{job="fleet-api"}: min=1 max=1 last=1' in result.content[0].text


@pytest.mark.anyio
@respx.mock
async def test_tool_errors_are_returned_as_text(server):
    # Same behaviour as in the agent loop: errors become readable text, not exceptions
    respx.get(f"{API}/health").mock(side_effect=httpx.ConnectError("refused"))
    respx.get(f"{PROM}/api/v1/query").mock(side_effect=httpx.ConnectError("refused"))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("get_service_health", {})
    assert "API /health: ERROR: could not connect (ConnectError)" in result.content[0].text
    assert not result.is_error


def test_main_runs_the_stdio_transport(monkeypatch):
    from agent import mcp_server

    started = []

    class FakeServer:
        def run(self, transport):
            started.append(transport)

    monkeypatch.setattr(mcp_server, "create_server", lambda: FakeServer())
    mcp_server.main()
    assert started == ["stdio"]


@pytest.mark.anyio
@respx.mock
async def test_query_loki_through_mcp(tmp_path):
    loki = "http://loki.test"
    respx.get(f"{loki}/loki/api/v1/query_range").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "resultType": "streams",
                    "result": [{"stream": {"service": "api"}, "values": [["1", "a log line"]]}],
                }
            },
        )
    )
    server = create_server(Settings(loki_url=loki, runbook_path=tmp_path / "missing.md"))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("query_loki", {"logql": '{service="api"}', "limit": 5})
    assert "[api] a log line" in result.content[0].text
