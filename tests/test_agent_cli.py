import json

from agent import cli
from agent.llm import FakeProvider, LLMResponse
from agent.loop import Investigator


def test_parse_labels():
    assert cli.parse_labels(["vehicle_id=2", "severity=warning"]) == {
        "vehicle_id": "2",
        "severity": "warning",
    }


def test_cli_prints_report_as_json(monkeypatch, capsys):
    report = {
        "summary": "s",
        "root_cause_category": "unknown",
        "root_cause_explanation": "e",
        "evidence": [],
        "confidence": "low",
        "suggested_actions": [],
    }
    answer = LLMResponse(content=json.dumps(report))
    # No tools here: the first answer is sent back once for evidence, the second is kept
    fake = Investigator(FakeProvider([answer, answer]), tools={})
    monkeypatch.setattr(cli, "create_investigator", lambda settings: fake)

    assert cli.main(["HighAlertRate", "--label", "severity=warning"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["alert_name"] == "HighAlertRate"
    assert printed["stop_reason"] == "completed"
