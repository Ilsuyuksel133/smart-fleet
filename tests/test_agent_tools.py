import httpx
import pytest
import respx

from agent.config import Settings
from agent.tools import build_tools, clamp, run_tool, truncate

PROM = "http://prom.test"
LOKI = "http://loki.test"
API = "http://api.test"

RUNBOOK = """# Runbook

## FleetApiDown (critical)

**Symptom**
- API is down.

## VehicleOverheating (warning)

**Symptom**
- Too hot.
"""


@pytest.fixture
def settings(tmp_path):
    runbook = tmp_path / "RUNBOOK.md"
    runbook.write_text(RUNBOOK, encoding="utf-8")
    return Settings(
        prometheus_url=PROM,
        loki_url=LOKI,
        api_url=API,
        runbook_path=runbook,
        max_tool_output_chars=4000,
    )


@pytest.fixture
def tools(settings):
    return build_tools(settings)


def matrix(series):
    return {"status": "success", "data": {"resultType": "matrix", "result": series}}


# --- helpers ---


def test_truncate_keeps_short_text_and_marks_cut_text():
    assert truncate("short", 10) == "short"
    cut = truncate("x" * 25, 10)
    assert cut.startswith("x" * 10)
    assert "[truncated: 15 more characters]" in cut


def test_clamp_limits_and_defaults():
    assert clamp(500, 1, 60, default=15) == 60
    assert clamp(0, 1, 60, default=15) == 1
    assert clamp("30", 1, 60, default=15) == 30
    assert clamp("abc", 1, 60, default=15) == 15
    assert clamp(None, 1, 60, default=15) == 15


def test_tool_definitions_use_function_calling_format(tools):
    assert set(tools) == {"query_prometheus", "query_loki", "get_runbook", "get_service_health"}
    definition = tools["query_loki"].definition()
    assert definition["type"] == "function"
    assert definition["function"]["name"] == "query_loki"
    assert definition["function"]["parameters"]["required"] == ["logql"]


# --- run_tool: errors never escape ---


def test_run_tool_unknown_tool(tools):
    result = run_tool(tools, "delete_everything", {})
    assert result.startswith("ERROR: unknown tool 'delete_everything'")


def test_run_tool_invalid_arguments(tools):
    result = run_tool(tools, "get_runbook", {"wrong": "x"})
    assert result.startswith("ERROR: invalid arguments for get_runbook")


def test_run_tool_unexpected_exception(tools, monkeypatch):
    def boom(**_):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(tools["get_service_health"], "run", boom)
    result = run_tool(tools, "get_service_health", {})
    assert result == "ERROR: get_service_health failed: RuntimeError: kaboom"


# --- query_prometheus ---


@respx.mock
def test_query_prometheus_summarizes_series(tools):
    route = respx.get(f"{PROM}/api/v1/query_range").mock(
        return_value=httpx.Response(
            200,
            json=matrix(
                [
                    {
                        "metric": {"__name__": "temp", "vehicle_id": "1"},
                        "values": [[1, "70"], [2, "95.5"], [3, "80"]],
                    }
                ]
            ),
        )
    )
    result = run_tool(tools, "query_prometheus", {"promql": "temp", "minutes": 10})

    assert 'temp{vehicle_id="1"}: min=70 max=95.5 last=80 points=3' in result
    assert "last 10 min" in result
    params = route.calls.last.request.url.params
    assert params["query"] == "temp"
    assert float(params["end"]) - float(params["start"]) == pytest.approx(600, abs=1)


@respx.mock
def test_query_prometheus_clamps_time_range(tools):
    route = respx.get(f"{PROM}/api/v1/query_range").mock(
        return_value=httpx.Response(200, json=matrix([]))
    )
    result = run_tool(tools, "query_prometheus", {"promql": "up", "minutes": 10_000})

    assert "No data" in result
    assert "last 60 min" in result
    params = route.calls.last.request.url.params
    assert float(params["end"]) - float(params["start"]) == pytest.approx(3600, abs=1)


@respx.mock
def test_query_prometheus_limits_number_of_series(tools):
    series = [{"metric": {"vehicle_id": str(i)}, "values": [[1, "1"]]} for i in range(15)]
    respx.get(f"{PROM}/api/v1/query_range").mock(
        return_value=httpx.Response(200, json=matrix(series))
    )
    result = run_tool(tools, "query_prometheus", {"promql": "x"})
    assert "... 5 more series omitted" in result


@respx.mock
def test_query_prometheus_invalid_query(tools):
    respx.get(f"{PROM}/api/v1/query_range").mock(
        return_value=httpx.Response(
            400, json={"status": "error", "error": "parse error: unclosed left parenthesis"}
        )
    )
    result = run_tool(tools, "query_prometheus", {"promql": "rate("})
    assert result == "ERROR: HTTP 400: parse error: unclosed left parenthesis"


@respx.mock
def test_query_prometheus_timeout(tools):
    respx.get(f"{PROM}/api/v1/query_range").mock(side_effect=httpx.ReadTimeout("slow"))
    assert run_tool(tools, "query_prometheus", {"promql": "up"}) == "ERROR: request timed out"


@respx.mock
def test_query_prometheus_connection_error(tools):
    respx.get(f"{PROM}/api/v1/query_range").mock(side_effect=httpx.ConnectError("refused"))
    result = run_tool(tools, "query_prometheus", {"promql": "up"})
    assert result == "ERROR: could not connect (ConnectError)"


@respx.mock
def test_query_prometheus_truncates_long_output(settings):
    settings.max_tool_output_chars = 100
    series = [{"metric": {"vehicle_id": str(i)}, "values": [[1, "1"]]} for i in range(10)]
    respx.get(f"{PROM}/api/v1/query_range").mock(
        return_value=httpx.Response(200, json=matrix(series))
    )
    result = run_tool(build_tools(settings), "query_prometheus", {"promql": "x"})
    assert "[truncated:" in result


# --- query_loki ---


def streams(*items):
    return {"status": "success", "data": {"resultType": "streams", "result": list(items)}}


@respx.mock
def test_query_loki_merges_streams_newest_first(tools):
    route = respx.get(f"{LOKI}/loki/api/v1/query_range").mock(
        return_value=httpx.Response(
            200,
            json=streams(
                {"stream": {"service": "api"}, "values": [["100", "old api line"]]},
                {"stream": {"service": "agent"}, "values": [["300", "new agent line"]]},
                {"stream": {"service": "api"}, "values": [["200", "middle api line"]]},
            ),
        )
    )
    result = run_tool(tools, "query_loki", {"logql": '{service="api"}', "limit": 2})

    assert "2 newest matching lines" in result
    assert result.index("[agent] new agent line") < result.index("[api] middle api line")
    assert "old api line" not in result
    params = route.calls.last.request.url.params
    assert params["limit"] == "2"
    assert params["direction"] == "backward"


@respx.mock
def test_query_loki_clamps_limit(tools):
    route = respx.get(f"{LOKI}/loki/api/v1/query_range").mock(
        return_value=httpx.Response(200, json=streams())
    )
    result = run_tool(tools, "query_loki", {"logql": '{level="error"}', "limit": 9999})
    assert "No log lines matched." in result
    assert route.calls.last.request.url.params["limit"] == "50"


@respx.mock
def test_query_loki_metric_query_is_summarized(tools):
    respx.get(f"{LOKI}/loki/api/v1/query_range").mock(
        return_value=httpx.Response(
            200, json=matrix([{"metric": {"service": "api"}, "values": [[1, "3"], [2, "7"]]}])
        )
    )
    result = run_tool(tools, "query_loki", {"logql": 'count_over_time({service="api"}[1m])'})
    assert '{service="api"}: min=3 max=7 last=7 points=2' in result


@respx.mock
def test_query_loki_invalid_query_returns_plain_text_error(tools):
    respx.get(f"{LOKI}/loki/api/v1/query_range").mock(
        return_value=httpx.Response(400, text="parse error at line 1, col 10: syntax error")
    )
    result = run_tool(tools, "query_loki", {"logql": "{service="})
    assert result == "ERROR: HTTP 400: parse error at line 1, col 10: syntax error"


@respx.mock
def test_query_loki_connection_error(tools):
    respx.get(f"{LOKI}/loki/api/v1/query_range").mock(side_effect=httpx.ConnectError("down"))
    result = run_tool(tools, "query_loki", {"logql": '{service="api"}'})
    assert result == "ERROR: could not connect (ConnectError)"


@respx.mock
def test_query_loki_truncates_long_output(settings):
    settings.max_tool_output_chars = 200
    values = [[str(i), "x" * 100] for i in range(20)]
    respx.get(f"{LOKI}/loki/api/v1/query_range").mock(
        return_value=httpx.Response(
            200, json=streams({"stream": {"service": "api"}, "values": values})
        )
    )
    result = run_tool(build_tools(settings), "query_loki", {"logql": '{service="api"}'})
    assert "[truncated:" in result


# --- get_runbook ---


def test_get_runbook_returns_matching_section(tools):
    result = run_tool(tools, "get_runbook", {"alert_name": "FleetApiDown"})
    assert result.startswith("## FleetApiDown (critical)")
    assert "API is down." in result
    assert "VehicleOverheating" not in result


def test_get_runbook_is_case_insensitive(tools):
    result = run_tool(tools, "get_runbook", {"alert_name": "vehicleoverheating"})
    assert result.startswith("## VehicleOverheating (warning)")


def test_get_runbook_unknown_alert_lists_sections(tools):
    result = run_tool(tools, "get_runbook", {"alert_name": "DiskFull"})
    assert "No runbook section for 'DiskFull'" in result
    assert "FleetApiDown (critical)" in result


def test_get_runbook_missing_file(settings, tmp_path):
    settings.runbook_path = tmp_path / "missing.md"
    result = run_tool(build_tools(settings), "get_runbook", {"alert_name": "FleetApiDown"})
    assert result == "ERROR: runbook not readable (FileNotFoundError)"


def test_get_runbook_truncates_long_section(settings):
    settings.runbook_path.write_text("## FleetApiDown\n" + "x" * 500, encoding="utf-8")
    settings.max_tool_output_chars = 100
    result = run_tool(build_tools(settings), "get_runbook", {"alert_name": "FleetApiDown"})
    assert "[truncated:" in result


def test_real_runbook_has_a_section_for_every_alert():
    # The agent relies on these headings; keep docs/RUNBOOK.md in sync with alert_rules.yml
    tools = build_tools(Settings())
    for alert in ["FleetApiDown", "VehicleOverheating", "HighAlertRate"]:
        assert run_tool(tools, "get_runbook", {"alert_name": alert}).startswith(f"## {alert}")


# --- get_service_health ---


@respx.mock
def test_get_service_health_reports_api_and_targets(tools):
    respx.get(f"{API}/health").mock(
        return_value=httpx.Response(200, json={"status": "ok", "db": "ok"})
    )
    respx.get(f"{PROM}/api/v1/query").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [
                        {"metric": {"job": "fleet-api", "instance": "api:8000"}, "value": [1, "1"]},
                        {"metric": {"job": "other", "instance": "x:1"}, "value": [1, "0"]},
                    ],
                },
            },
        )
    )
    result = run_tool(tools, "get_service_health", {})
    assert 'API /health: HTTP 200 {"status":"ok","db":"ok"}' in result
    assert 'Prometheus target {instance="api:8000", job="fleet-api"}: UP' in result
    assert 'Prometheus target {instance="x:1", job="other"}: DOWN' in result


@respx.mock
def test_get_service_health_reports_each_failure_separately(tools):
    respx.get(f"{API}/health").mock(side_effect=httpx.ConnectError("refused"))
    respx.get(f"{PROM}/api/v1/query").mock(return_value=httpx.Response(503, text="unavailable"))
    result = run_tool(tools, "get_service_health", {})
    assert "API /health: ERROR: could not connect (ConnectError)" in result
    assert "Prometheus 'up' query: ERROR: HTTP 503: unavailable" in result


@respx.mock
def test_query_prometheus_unexpected_response_shape(tools):
    # e.g. a proxy answering 200 with an unrelated body
    respx.get(f"{PROM}/api/v1/query_range").mock(return_value=httpx.Response(200, json={}))
    result = run_tool(tools, "query_prometheus", {"promql": "up"})
    assert result == "ERROR: KeyError: 'data'"
