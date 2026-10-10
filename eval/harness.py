"""Evaluation harness: inject a fault, let the agent investigate, score the result.

The orchestration only talks to two small interfaces, `Environment` (Docker
containers, simulator mode, Prometheus alerts) and `AgentClient` (the agent's
HTTP API). run_eval.py provides the real implementations; the tests provide
fakes, so the harness logic is tested without Docker or a model.
"""

import statistics
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel


class Scenario(BaseModel):
    name: str
    description: str
    alert: str  # the alert the agent is asked to investigate
    expected_category: str
    accept_low_confidence: bool = False  # for the control scenario
    simulator_mode: str = "calm"
    stop_services: list[str] = []
    wait_for_alert: str | None = None  # wait until Prometheus fires this alert
    timeout_seconds: float = 180  # max wait for wait_for_alert
    settle_seconds: float = 0  # fixed wait instead of wait_for_alert


def load_scenarios(directory: Path) -> list[Scenario]:
    """All scenario files in name order (1_..., 2_...)."""
    return [
        Scenario.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        for path in sorted(directory.glob("*.yaml"))
    ]


class Environment(Protocol):
    def ensure_vehicles(self, count: int) -> None: ...
    def set_simulator_mode(self, mode: str) -> None: ...
    def stop(self, service: str) -> None: ...
    def start(self, service: str) -> None: ...
    def firing_alerts(self) -> set[str]: ...
    def alert_labels(self, alert_name: str) -> dict[str, str]: ...
    def sleep(self, seconds: float) -> None: ...


class AgentClient(Protocol):
    def info(self) -> dict[str, Any]: ...
    def investigate(self, alert_name: str, labels: dict[str, str]) -> int: ...
    def wait_for_report(self, investigation_id: int, timeout: float) -> dict[str, Any]: ...


@dataclass
class RunResult:
    scenario: str
    run: int
    # ok | injection_failed (the fault did not show up) | agent_failed (no report)
    status: str
    clean_start: bool  # no alert was firing before the fault was injected
    category: str | None = None
    confidence: str | None = None
    correct: bool | None = None  # None when the run could not be scored
    steps: int | None = None
    duration_seconds: float | None = None
    stop_reason: str | None = None
    summary: str | None = None


def is_correct(scenario: Scenario, report: dict[str, Any]) -> bool:
    """Deterministic scoring: compare the category (no fuzzy text matching)."""
    if report["root_cause_category"] == scenario.expected_category:
        return True
    return scenario.accept_low_confidence and report["confidence"] == "low"


class Evaluator:
    def __init__(
        self,
        env: Environment,
        agent: AgentClient,
        poll_seconds: float = 10,
        clean_timeout: float = 480,
        report_timeout: float = 600,
        clock: Callable[[], float] = time.monotonic,
        log: Callable[[str], None] = print,
    ):
        self.env = env
        self.agent = agent
        self.poll_seconds = poll_seconds
        # HighAlertRate uses rate(...[5m]), so it can take minutes to clear
        self.clean_timeout = clean_timeout
        self.report_timeout = report_timeout
        self.clock = clock
        self.log = log

    def run(self, scenarios: list[Scenario], runs: int) -> list[RunResult]:
        """Run every scenario `runs` times, always from a clean system."""
        results = []
        # The fault modes assume several vehicles (e.g. "storm" needs enough
        # ERROR readings per second to exceed the HighAlertRate threshold).
        self.env.ensure_vehicles(3)
        # Alertmanager would start its own investigations of the injected
        # faults and compete with the evaluation, so it is paused meanwhile.
        self.env.stop("alertmanager")
        try:
            for run in range(1, runs + 1):
                for scenario in scenarios:
                    results.append(self.run_scenario(scenario, run))
        finally:
            self.env.set_simulator_mode("random")
            self.env.start("alertmanager")
        return results

    def run_scenario(self, scenario: Scenario, run: int) -> RunResult:
        self.log(f"[{scenario.name} #{run}] waiting for a clean system")
        self.env.set_simulator_mode("calm")
        clean = self.wait_until(lambda: not self.env.firing_alerts(), self.clean_timeout)
        if not clean:
            self.log(f"[{scenario.name} #{run}] still firing: {sorted(self.env.firing_alerts())}")

        try:
            # --- 1. Inject the fault ---
            self.log(f"[{scenario.name} #{run}] injecting fault")
            self.env.set_simulator_mode(scenario.simulator_mode)
            for service in scenario.stop_services:
                self.env.stop(service)

            # --- 2. Wait until the fault is visible (or just let it settle) ---
            if scenario.wait_for_alert:
                fired = self.wait_until(
                    lambda: scenario.wait_for_alert in self.env.firing_alerts(),
                    scenario.timeout_seconds,
                )
                if not fired:
                    self.log(f"[{scenario.name} #{run}] {scenario.wait_for_alert} never fired")
                    return RunResult(scenario.name, run, "injection_failed", clean)
            if scenario.settle_seconds:
                self.env.sleep(scenario.settle_seconds)

            # --- 3. Let the agent investigate and score the report ---
            # Pass the labels of the firing alert, as Alertmanager would (e.g.
            # which vehicle is overheating). Without them the model has to guess.
            labels = self.env.alert_labels(scenario.alert)
            investigation_id = self.agent.investigate(scenario.alert, labels)
            self.log(f"[{scenario.name} #{run}] investigation {investigation_id} started")
            detail = self.agent.wait_for_report(investigation_id, self.report_timeout)
            report = detail.get("report")
            if detail.get("status") != "done" or not report:
                return RunResult(scenario.name, run, "agent_failed", clean)

            result = RunResult(
                scenario=scenario.name,
                run=run,
                status="ok",
                clean_start=clean,
                category=report["root_cause_category"],
                confidence=report["confidence"],
                correct=is_correct(scenario, report),
                steps=report["steps_used"],
                duration_seconds=report["duration_seconds"],
                stop_reason=report["stop_reason"],
                summary=report["summary"],
            )
            self.log(
                f"[{scenario.name} #{run}] {result.category} ({result.confidence}) "
                f"-> {'correct' if result.correct else 'WRONG'}"
            )
            return result
        finally:
            # --- 4. Undo the fault, even if something above failed ---
            for service in scenario.stop_services:
                self.env.start(service)
            self.env.set_simulator_mode("calm")

    def wait_until(self, condition: Callable[[], bool], timeout: float) -> bool:
        deadline = self.clock() + timeout
        while True:
            if condition():
                return True
            if self.clock() >= deadline:
                return False
            self.env.sleep(self.poll_seconds)


# --- Reporting ---


def summarize(results: list[RunResult], scenarios: list[Scenario]) -> list[dict[str, Any]]:
    rows = []
    for scenario in scenarios:
        mine = [r for r in results if r.scenario == scenario.name]
        scored = [r for r in mine if r.correct is not None]
        correct = sum(1 for r in scored if r.correct)
        rows.append(
            {
                "scenario": scenario.name,
                "expected": scenario.expected_category
                + (" (or low confidence)" if scenario.accept_low_confidence else ""),
                "runs": len(mine),
                "scored": len(scored),
                "correct": correct,
                "accuracy": f"{correct / len(scored):.0%}" if scored else "n/a",
                "avg_steps": mean([r.steps for r in scored]),
                "avg_duration_s": mean([r.duration_seconds for r in scored]),
                "not_scored": len(mine) - len(scored),
            }
        )
    return rows


def mean(values: list[float | int | None]) -> str:
    numbers = [v for v in values if v is not None]
    return f"{statistics.mean(numbers):.1f}" if numbers else "n/a"


def render_markdown(
    results: list[RunResult], scenarios: list[Scenario], metadata: dict[str, Any]
) -> str:
    scored = [r for r in results if r.correct is not None]
    total_correct = sum(1 for r in scored if r.correct)
    lines = [
        "# Incident agent evaluation results",
        "",
        "Generated by `eval/run_eval.py`. Every run starts from a clean system "
        "(simulator in `calm` mode, no alert firing), injects one fault, waits until it is "
        "visible, asks the agent to investigate and compares the root cause category.",
        "",
        "| Setting | Value |",
        "|---|---|",
        *[f"| {key} | {value} |" for key, value in metadata.items()],
        "",
        f"**Overall: {total_correct}/{len(scored)} correct**"
        + (f" ({total_correct / len(scored):.0%})" if scored else ""),
        "",
        "## Per scenario",
        "",
        "| Scenario | Expected | Correct | Accuracy | Avg steps | Avg duration (s) | Not scored |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in summarize(results, scenarios):
        lines.append(
            f"| {row['scenario']} | {row['expected']} | {row['correct']}/{row['scored']} "
            f"| {row['accuracy']} | {row['avg_steps']} | {row['avg_duration_s']} "
            f"| {row['not_scored']} |"
        )
    lines += [
        "",
        "## All runs",
        "",
        "| Scenario | Run | Status | Clean start | Category | Confidence | Correct | Steps "
        "| Duration (s) | Stop reason | Summary |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        correct = {True: "✅", False: "❌", None: "–"}[r.correct]
        summary = (r.summary or "").replace("|", "/").replace("\n", " ")
        lines.append(
            f"| {r.scenario} | {r.run} | {r.status} | {'yes' if r.clean_start else 'no'} "
            f"| {r.category or '–'} | {r.confidence or '–'} | {correct} | {r.steps or '–'} "
            f"| {r.duration_seconds if r.duration_seconds is not None else '–'} "
            f"| {r.stop_reason or '–'} | {summary} |"
        )
    return "\n".join(lines) + "\n"


def results_as_dicts(results: list[RunResult]) -> list[dict[str, Any]]:
    return [asdict(r) for r in results]
