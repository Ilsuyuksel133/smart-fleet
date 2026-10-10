# Incident agent evaluation

Measures how often the agent finds the right root cause category for a known, injected fault.

## Method

`python -m eval.run_eval --runs 3` (from the repository root, with the stack running):

1. **Clean start:** switch the simulator to `calm` mode (60–78 °C, status OK) and wait until no alert is firing.
2. **Inject the fault** described in `scenarios/*.yaml`, e.g. stop the API container or switch the simulator to `overheat` / `storm`.
3. **Wait until the fault is visible**, i.e. Prometheus fires the expected alert. If it never fires, the run is recorded as `injection_failed` and is not scored.
4. **Ask the agent** to investigate the alert via `POST /investigate`, passing the labels of the firing alert (like Alertmanager does).
5. **Score deterministically:** the report's `root_cause_category` must equal the expected category. For the control scenario a `low` confidence also counts.
6. **Undo the fault.**

Alertmanager is paused during the evaluation, so it does not start competing investigations. It is restarted at the end. The simulator is switched back to its default `random` mode.

| Scenario | Fault | Expected |
|---|---|---|
| `api_down` | API container stopped → `FleetApiDown` | `service_down` |
| `overheating` | one vehicle reports 95–100 °C → `VehicleOverheating` | `sensor_anomaly` |
| `alert_storm` | every vehicle reports `ERROR` → `HighAlertRate` | `alert_storm` |
| `control` | healthy system, agent asked about `FleetApiDown` anyway | `unknown` or low confidence |

## Results

See [results.md](results.md) (generated) and [results.json](results.json) (raw).

Latest run: `qwen3:8b`, think off, Apple M2 / 16 GB. **11 of 12 runs correct (92%).**

| Scenario | Correct | Avg duration |
|---|---|---|
| api_down | 2/3 | 84 s |
| overheating | 3/3 | 87 s |
| alert_storm | 3/3 | 41 s |
| control | 3/3 | 40 s |

### The one failure

In `api_down` run 3, the agent had already collected the right evidence:
- `get_service_health` showed the API as DOWN
- it had read the runbook

Then its 4th LLM call hit the 120 s Ollama timeout (`stop_reason: llm_error`). Earlier calls took 2–42 s. As designed, the loop did not crash: it wrote an `unknown` / low report that kept the evidence. Still, one slow model response lost an otherwise correct investigation. Possible improvements:
- cap the number of generated tokens
- retry a timed-out call once

### Caveats

- **Small sample:** 3 runs per scenario on a single machine. The accuracy is indicative, not statistically significant.
- **Clear-cut faults:** each scenario injects exactly one fault, and the categories map closely to the alert names. Real incidents are messier.
- **Summaries vary in quality:** a correct category does not mean the explanation is perfect. For example, control run 2 contains a wrong PromQL label (`up{job="api"}`) in its reasoning, although the conclusion (`unknown`, low) is right.

## Problems found while building the evaluation

Two earlier evaluation attempts were stopped because the *harness* produced invalid results. These problems were in the harness, not in the agent:

1. **Missing labels:** the harness first called `/investigate` with the alert name only. In the overheating scenario the model did not know which vehicle was affected, guessed `vehicle_id="3"` (taken from a runbook example), found no data and answered `unknown`. Alertmanager always sends the labels, so the harness now passes the labels of the firing alert too.
2. **Too few vehicles:** the simulator only creates its three vehicles if the API has none. After a fresh start the smoke test had already created one, so only that single vehicle was simulated. The `storm` mode then reached about 0.33 alerts/s and never crossed the 0.5/s threshold of `HighAlertRate`. The harness now makes sure at least three vehicles exist before it starts.

## Tests

The harness logic is covered by unit tests with a fake environment and a fake agent (`tests/test_eval_harness.py`, `tests/test_eval_runner.py`). One test runs it against the real agent HTTP API with the `FakeProvider`. They run in CI; the evaluation with the real model only runs locally.
