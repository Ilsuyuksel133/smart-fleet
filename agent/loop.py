"""The agent loop: let the LLM investigate an alert with read-only tools.

This is a plain, framework-free implementation of the "tool calling" pattern:

    1. Start the conversation with a system prompt and the alert.
    2. Call the LLM, offering it the tool definitions.
    3. If it asks for tools, run them, add the results to the conversation
       and go back to step 2.
    4. If it answers without tools, that answer is the report: parse it.

The LLM decides *which* data to look at; the loop decides *how much* it may
do. Guard rails (step limit, time limit, duplicate-call detection, one retry
for invalid JSON) make sure an investigation always ends with a report,
never with an exception or an endless loop.
"""

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from agent import metrics
from agent.config import Settings
from agent.llm import LLMProvider, Message, ToolCall, get_provider
from agent.report import Alert, Evidence, RCAReport, RootCauseCategory, parse_model_report
from agent.tools import Tool, build_tools, run_tool

log = logging.getLogger("fleet-agent")

SYSTEM_PROMPT = """You are an SRE assistant investigating an alert in "smart-fleet", a vehicle \
monitoring system. Services: api (FastAPI), simulator (sends sensor data), dashboard, \
prometheus, loki, alloy, grafana.

Use the tools to collect evidence before concluding. A good order is:
1. get_runbook for the alert, 2. get_service_health, 3. targeted Prometheus/Loki queries.
If a tool returns ERROR, read the message, fix the query and try again.
All tools are read-only. You only report; a human decides what to do.

Root cause categories:
- service_down: a service (usually the API) is down or unreachable
- sensor_anomaly: vehicles report abnormal readings (e.g. too high temperature)
- alert_storm: an unusually high number of alerts in a short time
- unknown: the evidence does not clearly support any category above

When you are done, answer with ONLY a JSON object, no other text:
{
  "summary": "one sentence",
  "root_cause_category": "service_down | sensor_anomaly | alert_storm | unknown",
  "root_cause_explanation": "what happened and why, based on the evidence",
  "evidence": [{"tool": "tool name", "query": "query or arguments", "finding": "what it showed"}],
  "confidence": "low | medium | high",
  "suggested_actions": ["concrete step, referencing the runbook where possible"]
}
Only cite evidence you actually got from a tool. If the evidence is weak or contradictory, \
use "unknown" and "low" confidence."""

FIX_JSON_PROMPT = (
    "Your answer could not be used: {error}. "
    "Reply again with ONLY the JSON object described in the instructions."
)

NO_EVIDENCE_PROMPT = (
    "You have not used any tool yet, so your answer is not based on evidence. "
    "Use the tools to check the system first, then give your final JSON answer."
)

DUPLICATE_CALL_MESSAGE = (
    "ERROR: you already made this exact call; its result is above. "
    "Use different arguments, another tool, or give your final JSON answer."
)


class Investigator:
    def __init__(
        self,
        provider: LLMProvider,
        tools: dict[str, Tool],
        max_steps: int = 8,
        max_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.provider = provider
        self.tools = tools
        self.max_steps = max_steps
        self.max_seconds = max_seconds
        # Injectable clock so tests can simulate a slow model without waiting
        self.clock = clock

    def investigate(self, alert: Alert) -> RCAReport:
        started = self.clock()
        messages: list[Message] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": describe_alert(alert)},
        ]
        tool_definitions = [tool.definition() for tool in self.tools.values()]
        # (tool, arguments) pairs already executed, to catch the model repeating itself
        seen_calls: set[tuple[str, str]] = set()
        # Every tool call and its result, used as evidence if the model never finishes
        trace: list[Evidence] = []
        json_retry_used = False
        evidence_nudge_used = False

        log.info("investigation started", extra={"alert_name": alert.name})

        # Each iteration is one LLM call ("step"). The for-loop itself is the
        # step limit: it cannot run forever, whatever the model does.
        for step in range(1, self.max_steps + 1):
            if self.clock() - started > self.max_seconds:
                return self._fallback(alert, "timeout", step - 1, started, trace)

            try:
                llm_started = self.clock()
                response = self.provider.chat(messages, tool_definitions)
            except Exception as error:
                # Model not running, crashed, timed out... never crash the investigation
                log.error("llm call failed", extra={"step": step, "error": str(error)})
                return self._fallback(alert, "llm_error", step, started, trace)
            log.info(
                "llm call",
                extra={
                    "alert_name": alert.name,
                    "step": step,
                    "duration_ms": round((self.clock() - llm_started) * 1000),
                    "tool_calls": [call.name for call in response.tool_calls],
                },
            )
            # The assistant's turn must be part of the history, so the model
            # sees which tools it asked for when it gets their results.
            messages.append(response.as_message())

            # --- The model wants data: run the tools and loop again ---
            if response.tool_calls:
                for call in response.tool_calls:
                    result = self._run_call(alert, step, call, seen_calls, trace)
                    messages.append(tool_result_message(call, result))
                continue

            # --- No tool calls: this is the final answer ---

            # A conclusion without any tool result is just a guess from the alert
            # name. Ask once for evidence; small models sometimes skip the tools.
            if not trace and not evidence_nudge_used:
                evidence_nudge_used = True
                log.warning("answer without evidence, asking to use tools", extra={"step": step})
                messages.append({"role": "user", "content": NO_EVIDENCE_PROMPT})
                continue

            try:
                model_report = parse_model_report(response.content)
            except ValueError as error:
                if json_retry_used:
                    return self._fallback(alert, "invalid_output", step, started, trace)
                # Small models often get the format almost right; one precise
                # correction request fixes most of these cases.
                json_retry_used = True
                log.warning("invalid report, asking for a fix", extra={"step": step})
                messages.append(
                    {"role": "user", "content": FIX_JSON_PROMPT.format(error=short(error))}
                )
                continue

            report = RCAReport(
                **model_report.model_dump(),
                alert_name=alert.name,
                steps_used=step,
                duration_seconds=round(self.clock() - started, 2),
            )
            if not trace:
                # The model insisted on answering without data: keep its answer,
                # but it cannot claim more than low confidence.
                report.confidence = "low"
            self._log_finished(report)
            return report

        return self._fallback(alert, "max_steps", self.max_steps, started, trace)

    def _run_call(
        self,
        alert: Alert,
        step: int,
        call: ToolCall,
        seen_calls: set[tuple[str, str]],
        trace: list[Evidence],
    ) -> str:
        """Run one tool call (or refuse a duplicate) and log it."""
        # sort_keys: {"a": 1, "b": 2} and {"b": 2, "a": 1} are the same call
        key = (call.name, json.dumps(call.arguments, sort_keys=True))
        tool_started = self.clock()
        if key in seen_calls:
            # Re-running would return the same data and waste a step; telling
            # the model is usually enough to make it move on.
            result = DUPLICATE_CALL_MESSAGE
        else:
            seen_calls.add(key)
            result = run_tool(self.tools, call.name, call.arguments)
            metrics.TOOL_CALLS.labels(call.name).inc()
            trace.append(Evidence(tool=call.name, query=key[1], finding=short(result, 300)))

        log.info(
            "tool call",
            extra={
                "alert_name": alert.name,
                "step": step,
                "tool": call.name,
                "arguments": call.arguments,
                "duration_ms": round((self.clock() - tool_started) * 1000),
                "duplicate": result is DUPLICATE_CALL_MESSAGE,
                "result_preview": short(result, 200),
            },
        )
        return result

    def _fallback(
        self, alert: Alert, reason: str, steps: int, started: float, trace: list[Evidence]
    ) -> RCAReport:
        """A report written by the loop when the model could not finish.

        It is always "unknown" with low confidence, but still useful: it lists
        everything the tools returned, so a human can continue from there.
        """
        report = RCAReport(
            alert_name=alert.name,
            summary=f"Automatic investigation of {alert.name} did not finish ({reason}).",
            root_cause_category=RootCauseCategory.unknown,
            root_cause_explanation=FALLBACK_EXPLANATIONS[reason],
            evidence=trace,
            confidence="low",
            suggested_actions=[f"Follow the runbook section for {alert.name} manually."],
            steps_used=steps,
            duration_seconds=round(self.clock() - started, 2),
            stop_reason=reason,
        )
        self._log_finished(report)
        return report

    @staticmethod
    def _log_finished(report: RCAReport) -> None:
        log.info(
            "investigation finished",
            extra={
                "alert_name": report.alert_name,
                "category": report.root_cause_category.value,
                "confidence": report.confidence,
                "steps_used": report.steps_used,
                "duration_seconds": report.duration_seconds,
                "stop_reason": report.stop_reason,
            },
        )


FALLBACK_EXPLANATIONS = {
    "max_steps": "The step limit was reached before the model gave a final answer.",
    "timeout": "The time limit was reached before the model gave a final answer.",
    "invalid_output": "The model's final answer was not a valid report, even after a retry.",
    "llm_error": "The language model could not be reached or returned an error.",
}


def describe_alert(alert: Alert) -> str:
    """The first user message: everything known about the alert."""
    details: dict[str, Any] = {"alert": alert.name}
    if alert.labels:
        details["labels"] = alert.labels
    if alert.annotations:
        details["annotations"] = alert.annotations
    return "Investigate this alert:\n" + json.dumps(details, indent=2)


def tool_result_message(call: ToolCall, result: str) -> Message:
    """A tool result in the chat format, linked to the call that requested it."""
    message: Message = {"role": "tool", "tool_name": call.name, "content": result}
    if call.id:
        message["tool_call_id"] = call.id
    return message


def short(value: Any, limit: int = 300) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def create_investigator(settings: Settings) -> Investigator:
    """An investigator wired with the configured LLM provider and tools."""
    return Investigator(
        provider=get_provider(settings),
        tools=build_tools(settings),
        max_steps=settings.agent_max_steps,
        max_seconds=settings.agent_max_seconds,
    )
