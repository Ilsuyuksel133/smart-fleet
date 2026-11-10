from agent.config import Settings
from agent.rag import FakeEmbedder, RunbookSearch
from eval.run_retrieval_eval import (
    Question,
    Ranked,
    evaluate,
    load_questions,
    metrics,
    render_markdown,
)

RUNBOOK = """## FleetApiDown (critical)

The API container is stopped.

## No logs in Loki

Alloy cannot read the docker socket, Loki shows no log lines.
"""


def test_metrics_from_ranks():
    q = Question("q", "A")
    ranked = [Ranked(q, ["A", "B"]), Ranked(q, ["B", "C", "A"]), Ranked(q, ["B", "C", "D", "A"])]
    assert [r.rank for r in ranked] == [1, 3, 4]
    assert metrics(ranked) == {"hit@1": 1 / 3, "hit@3": 2 / 3, "mrr": (1 + 1 / 3 + 1 / 4) / 3}
    assert Ranked(q, ["B"]).rank is None


def test_questions_file_names_existing_sections():
    questions = load_questions()
    assert len(questions) >= 15
    runbook = Settings().runbook_path.read_text(encoding="utf-8")
    for question in questions:
        assert f"## {question.expected}" in runbook


def test_evaluate_and_render(tmp_path):
    runbook = tmp_path / "RUNBOOK.md"
    runbook.write_text(RUNBOOK, encoding="utf-8")
    settings = Settings(runbook_path=runbook, runbook_index_path=tmp_path / "index.json")
    questions = [
        Question("loki shows no log lines", "No logs in Loki"),
        Question("api container stopped", "FleetApiDown"),
    ]
    results = evaluate(RunbookSearch(settings, FakeEmbedder()), questions)

    assert set(results) == {"embedding", "keyword"}
    assert [r.rank for r in results["embedding"]] == [1, 1]
    text = render_markdown(
        results,
        {
            "date": "2026-11-10",
            "embedder": "fake",
            "chunks": "2",
            "chunk_chars": "800",
            "questions": "2",
        },
    )
    assert "| embedding | 100% | 100% | 1.00 |" in text
    assert "| api container stopped | FleetApiDown | 1 | 1 |" in text


def test_main_writes_the_report(tmp_path, monkeypatch, capsys):
    from eval import run_retrieval_eval

    output = tmp_path / "results.md"
    monkeypatch.setattr(run_retrieval_eval, "INDEX_PATH", tmp_path / "index.json")
    monkeypatch.setattr("sys.argv", ["run_retrieval_eval", "--fake", "--output", str(output)])
    run_retrieval_eval.main()

    assert output.read_text().startswith("# Runbook retrieval evaluation")
    assert "Embedder: `fake`" in output.read_text()
    assert "embedding hit@1=" in capsys.readouterr().out
