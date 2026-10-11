"""Run the agent evaluation against the local Docker Compose stack.

Usage (from the repository root, with the stack running):

    python -m eval.run_eval --runs 3

It stops and starts containers and switches the simulator mode, so run it on a
local development stack only. Results go to eval/results.md and eval/results.json.
"""

import argparse
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from eval.harness import Evaluator, load_scenarios, render_markdown, results_as_dicts

ROOT = Path(__file__).resolve().parent.parent


class DockerEnvironment:
    """Controls the Compose stack and reads alerts from Prometheus."""

    def __init__(self, prometheus_url: str, api_url: str):
        self.prometheus_url = prometheus_url
        self.api_url = api_url

    def compose(self, *args: str, env: dict[str, str] | None = None) -> None:
        subprocess.run(
            ["docker", "compose", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            env={**os.environ, **(env or {})},
        )

    def ensure_vehicles(self, count: int) -> None:
        """Create vehicles until the API has at least `count` of them."""
        existing = httpx.get(f"{self.api_url}/vehicles", timeout=10).json()
        for number in range(len(existing) + 1, count + 1):
            httpx.post(
                f"{self.api_url}/vehicles", json={"name": f"eval-vehicle-{number}"}, timeout=10
            ).raise_for_status()

    def set_simulator_mode(self, mode: str) -> None:
        # --no-deps: do not start the (possibly stopped) API as a dependency.
        # --force-recreate: the simulator reads the vehicle list only at startup.
        self.compose(
            "up",
            "-d",
            "--no-deps",
            "--force-recreate",
            "simulator",
            env={"SIMULATOR_MODE": mode},
        )

    def stop(self, service: str) -> None:
        self.compose("stop", service)

    def start(self, service: str) -> None:
        self.compose("start", service)

    def _firing(self) -> list[dict[str, Any]]:
        response = httpx.get(f"{self.prometheus_url}/api/v1/alerts", timeout=10)
        response.raise_for_status()
        return [a for a in response.json()["data"]["alerts"] if a["state"] == "firing"]

    def firing_alerts(self) -> set[str]:
        return {alert["labels"]["alertname"] for alert in self._firing()}

    def alert_labels(self, alert_name: str) -> dict[str, str]:
        """Labels shared by all firing instances of the alert (like Alertmanager's
        commonLabels when grouping by alert name). Empty if it is not firing."""
        instances = [a["labels"] for a in self._firing() if a["labels"]["alertname"] == alert_name]
        if not instances:
            return {}
        return {
            key: value
            for key, value in instances[0].items()
            if all(other.get(key) == value for other in instances)
        }

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class HttpAgentClient:
    def __init__(self, agent_url: str):
        self.agent_url = agent_url

    def info(self) -> dict[str, Any]:
        return httpx.get(f"{self.agent_url}/health", timeout=10).json()

    def investigate(self, alert_name: str, labels: dict[str, str]) -> int:
        response = httpx.post(
            f"{self.agent_url}/investigate",
            json={"alert_name": alert_name, "labels": labels},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()["investigation_id"]

    def wait_for_report(self, investigation_id: int, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            detail = httpx.get(f"{self.agent_url}/reports/{investigation_id}", timeout=10).json()
            if detail["status"] in ("done", "failed") or time.monotonic() > deadline:
                return detail
            time.sleep(5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the incident agent.")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--only", nargs="*", help="scenario names to run (default: all)")
    parser.add_argument("--scenarios", type=Path, default=ROOT / "eval" / "scenarios")
    parser.add_argument("--output", type=Path, default=ROOT / "eval" / "results.md")
    parser.add_argument("--agent-url", default="http://localhost:8100")
    parser.add_argument("--prometheus-url", default="http://localhost:9090")
    parser.add_argument("--api-url", default="http://localhost:8000")
    args = parser.parse_args(argv)

    scenarios = load_scenarios(args.scenarios)
    if args.only:
        scenarios = [s for s in scenarios if s.name in args.only]

    agent = HttpAgentClient(args.agent_url)
    info = agent.info()
    started = datetime.now(UTC)
    print(f"Evaluating {len(scenarios)} scenarios x {args.runs} runs with {info}")

    evaluator = Evaluator(DockerEnvironment(args.prometheus_url, args.api_url), agent)
    results = evaluator.run(scenarios, args.runs)

    metadata = {
        "Date (UTC)": started.strftime("%Y-%m-%d %H:%M"),
        "LLM provider": info.get("llm_provider"),
        "Model": info.get("llm_model") or "–",
        "Runs per scenario": args.runs,
        "Total wall time (min)": round((datetime.now(UTC) - started).total_seconds() / 60, 1),
    }
    args.output.write_text(render_markdown(results, scenarios, metadata), encoding="utf-8")
    args.output.with_suffix(".json").write_text(
        json.dumps({"metadata": metadata, "results": results_as_dicts(results)}, indent=2),
        encoding="utf-8",
    )
    print(f"Results written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
