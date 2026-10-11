"""Runs investigations in the background, one at a time.

Why a queue with a single worker thread:
- Alertmanager expects a fast response, but an investigation with a local
  model takes about a minute. The webhook only enqueues and returns 202.
- A local LLM handles one request at a time efficiently; running
  investigations in parallel would only make each of them slower.
- The same alert must not be investigated twice at the same time, and an
  alert that was just investigated is skipped for a while (cooldown), so an
  alert that keeps firing cannot keep the model busy forever.
"""

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from agent import metrics
from agent.loop import Investigator
from agent.report import Alert
from agent.storage import ReportStore

log = logging.getLogger("fleet-agent")


@dataclass
class SubmitResult:
    accepted: bool
    alert_name: str
    investigation_id: int | None = None
    reason: str = ""


class InvestigationService:
    def __init__(
        self,
        store: ReportStore,
        investigator: Investigator,
        cooldown_seconds: float = 900.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.store = store
        self.investigator = investigator
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock
        self.queue: queue.Queue[tuple[int, Alert]] = queue.Queue()
        # Alert names that are queued or running right now
        self.active: set[str] = set()
        # When each alert name was last investigated (for the cooldown)
        self.last_started: dict[str, float] = {}
        # submit() runs in web request threads, the worker in its own thread
        self.lock = threading.Lock()

    def submit(self, alert: Alert, trigger: str, respect_cooldown: bool = True) -> SubmitResult:
        """Queue an investigation unless the same alert is active or cooling down."""
        with self.lock:
            skip_reason = None
            last = self.last_started.get(alert.name)
            if alert.name in self.active:
                skip_reason = "already queued or running"
            elif respect_cooldown and last is not None:
                remaining = self.cooldown_seconds - (self.clock() - last)
                if remaining > 0:
                    skip_reason = f"cooldown ({remaining:.0f} s left)"
            if skip_reason is None:
                self.active.add(alert.name)
                self.last_started[alert.name] = self.clock()

        if skip_reason:
            log.info(
                "investigation skipped",
                extra={"alert_name": alert.name, "trigger": trigger, "reason": skip_reason},
            )
            return SubmitResult(False, alert.name, reason=skip_reason)

        investigation_id = self.store.create(alert, trigger)
        self.queue.put((investigation_id, alert))
        log.info(
            "investigation queued",
            extra={
                "alert_name": alert.name,
                "investigation_id": investigation_id,
                "trigger": trigger,
            },
        )
        return SubmitResult(True, alert.name, investigation_id=investigation_id)

    def process_next(self, timeout: float | None = None) -> bool:
        """Run the next queued investigation. Returns False if the queue stayed empty."""
        try:
            investigation_id, alert = self.queue.get(timeout=timeout)
        except queue.Empty:
            return False
        try:
            self.store.mark_running(investigation_id)
            report = self.investigator.investigate(alert)
            self.store.save_report(investigation_id, report)
            metrics.INVESTIGATIONS.labels(report.root_cause_category.value).inc()
            metrics.INVESTIGATION_DURATION.observe(report.duration_seconds)
            metrics.STEPS_PER_INVESTIGATION.observe(report.steps_used)
        except Exception as error:
            # The loop itself never raises; this protects against storage errors
            log.exception("investigation failed", extra={"investigation_id": investigation_id})
            self.store.mark_failed(investigation_id, f"{type(error).__name__}: {error}")
        finally:
            with self.lock:
                self.active.discard(alert.name)
            self.queue.task_done()
        return True

    def start_worker(self) -> threading.Thread:
        """Process the queue forever in a background (daemon) thread."""

        def work() -> None:
            while True:
                self.process_next()

        thread = threading.Thread(target=work, name="investigation-worker", daemon=True)
        thread.start()
        return thread
