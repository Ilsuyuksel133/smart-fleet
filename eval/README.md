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

See [results.md](results.md) (generated) and [results.json](results.json) (raw) for the latest run.

All runs: `qwen3:8b`, think off, Apple M2 / 16 GB, 3 runs per scenario.

| Scenario | Run A | Run B | Run C (latest) |
|---|---|---|---|
| api_down | 2/3 | 2/3 | 3/3 |
| overheating | 3/3 | 2/3 | 0/3 |
| alert_storm | 3/3 | 3/3 | 3/3 |
| control | 3/3 | 2/3 | 3/3 |
| **Total** | **11/12 (92%)** | **9/12 (75%)** | **9/12 (75%)** |

Code changes between the runs:
- **Run B:** the generated tokens are capped and a timed-out LLM call is retried once.
- **Run C:** the report retry uses structured output, rejected reports are logged, and the tool description lists the `job` values.

Differences of two or three answers between runs of 12 are within what small samples of a non-deterministic model show, so no single run should be read as a regression or an improvement. **Over all runs: 29/36 (81%).**

### Failures and what they show

| Run | Scenario | Result | What happened |
|---|---|---|---|
| A | api_down | unknown / low (`llm_error`) | The right evidence was collected, then one LLM call exceeded the 120 s timeout. Led to the token cap and retry in phase 5. |
| B | api_down | unknown / low (`invalid_output`) | The right evidence was collected (API down, `up` = 0), but the final answer was invalid JSON twice. |
| B | overheating | unknown / medium | Over-cautious: it saw 97.9 °C for the alerted vehicle but considered the evidence inconclusive. |
| B | control | service_down / medium | It queried `up{job="api"}` (the job is called `fleet-api`), got no data and concluded the API was not scraped, contradicting its own health check. |
| C | overheating (all 3) | unknown / medium | Every time it queried `fleet_alerts_total{type="high_temperature", vehicle_id="1"}`. That metric has no `vehicle_id` label, so the query returned no data. The model read this as "no high-temperature alerts" and called the evidence contradictory, although it had seen the temperature at 95–100 °C. |

The loop's guard rails held in every run: no crash, no endless loop, and every report contains the evidence that was collected. In run C no answer had to be retried for invalid JSON. The remaining failures are reasoning errors of a small local model.

The most frequent pattern (4 of 7 failures) is the same: **a query with a label that does not exist returns "no data", and the model takes that as evidence.** A possible next step is a "no data" message that reminds the model to check the label names.

### Caveats

- **Small sample:** 3 runs per scenario on a single machine. The two runs differ by three answers, so treat the numbers as indicative only.
- **Clear-cut faults:** each scenario injects exactly one fault, and the categories map closely to the alert names. Real incidents are messier.
- **Summaries vary in quality:** a correct category does not mean the explanation is perfect.

## Problems found while building the evaluation

Two earlier evaluation attempts were stopped because the *harness* produced invalid results. These problems were in the harness, not in the agent:

1. **Missing labels:** the harness first called `/investigate` with the alert name only. In the overheating scenario the model did not know which vehicle was affected, guessed `vehicle_id="3"` (taken from a runbook example), found no data and answered `unknown`. Alertmanager always sends the labels, so the harness now passes the labels of the firing alert too.
2. **Too few vehicles:** the simulator only creates its three vehicles if the API has none. After a fresh start the smoke test had already created one, so only that single vehicle was simulated. The `storm` mode then reached about 0.33 alerts/s and never crossed the 0.5/s threshold of `HighAlertRate`. The harness now makes sure at least three vehicles exist before it starts.

## Tests

The harness logic is covered by unit tests with a fake environment and a fake agent (`tests/test_eval_harness.py`, `tests/test_eval_runner.py`). One test runs it against the real agent HTTP API with the `FakeProvider`. They run in CI; the evaluation with the real model only runs locally.
