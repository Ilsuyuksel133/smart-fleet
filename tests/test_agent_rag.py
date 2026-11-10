import json

import httpx
import numpy as np
import pytest
import respx

from agent.config import Settings
from agent.rag import (
    FakeEmbedder,
    KeywordScorer,
    OllamaEmbedder,
    RunbookSearch,
    chunk_runbook,
    get_embedder,
)
from agent.tools import build_tools, run_tool

OLLAMA = "http://ollama.test"

LONG_CHECKS = "\n".join(f"docker compose logs --tail 50 service{i}" for i in range(30))

RUNBOOK = f"""# Runbook

Introduction that is not a section.

## FleetApiDown (critical)

**Symptom**
- The API container is stopped and requests fail.

## Database unreachable

**Symptom**
- The health endpoint returns 503 because MySQL refuses connections.

**Checks**
```bash
{LONG_CHECKS}

# a comment, not a heading
## also not a heading inside a code block
```

**Fix**
- Start the mysql container again.

---

## No logs in Loki

**Symptom**
- Log panels in Grafana are empty and Alloy reports push errors.
"""


@pytest.fixture
def settings(tmp_path):
    runbook = tmp_path / "RUNBOOK.md"
    runbook.write_text(RUNBOOK, encoding="utf-8")
    return Settings(
        llm_provider="fake",
        ollama_url=OLLAMA,
        runbook_path=runbook,
        runbook_index_path=tmp_path / "index" / "runbook_index.json",
        rag_chunk_chars=300,
        rag_min_score=0.0,
    )


class CountingEmbedder(FakeEmbedder):
    """FakeEmbedder that counts how many documents it embedded."""

    def __init__(self):
        super().__init__()
        self.documents = 0

    def embed(self, texts, kind):
        if kind == "document":
            self.documents += len(texts)
        return super().embed(texts, kind)


# --- Chunking ---


def test_chunks_follow_sections_and_skip_the_introduction():
    chunks = chunk_runbook(RUNBOOK, max_chars=300)
    sections = list(dict.fromkeys(chunk.section for chunk in chunks))
    assert sections == ["FleetApiDown (critical)", "Database unreachable", "No logs in Loki"]
    assert all("Introduction" not in chunk.text for chunk in chunks)
    # Short sections stay whole and use the plain title as their path
    assert chunks[0].heading_path == "FleetApiDown (critical)"
    assert chunks[0].id == "fleetapidown-critical-1"


def test_long_section_is_split_but_code_blocks_stay_whole():
    chunks = [
        c for c in chunk_runbook(RUNBOOK, max_chars=300) if c.section == "Database unreachable"
    ]
    assert len(chunks) == 3
    assert [c.heading_path for c in chunks] == [
        "Database unreachable > Symptom",
        "Database unreachable > Checks",
        "Database unreachable > Fix",
    ]
    checks = chunks[1].text
    # Longer than the limit, but the code block is not cut, blank line and "##" included
    assert len(checks) > 300
    assert checks.count("```") == 2
    assert "## also not a heading" in checks
    assert all("---" != line for chunk in chunks for line in chunk.text.splitlines())


# --- Index ---


def test_index_is_cached_and_rebuilt_when_the_runbook_changes(settings):
    embedder = CountingEmbedder()
    RunbookSearch(settings, embedder).warm_up()
    built = embedder.documents
    assert built > 0
    assert settings.runbook_index_path.exists()

    # A new process with the same runbook reads the vectors from the file
    RunbookSearch(settings, embedder).warm_up()
    assert embedder.documents == built

    # Changed runbook: new chunks, new vectors (also within the running process)
    search = RunbookSearch(settings, embedder)
    search.warm_up()
    settings.runbook_path.write_text(RUNBOOK + "\n## New section\n\nNew text.\n", encoding="utf-8")
    search.search("new text", top_k=1)
    assert embedder.documents > built
    assert "New section" in search.section_titles()


def test_cache_of_another_embedder_is_not_used(settings):
    RunbookSearch(settings, FakeEmbedder()).warm_up()
    data = json.loads(settings.runbook_index_path.read_text())
    data["key"]["embedder"] = "ollama/other-model"
    settings.runbook_index_path.write_text(json.dumps(data))

    embedder = CountingEmbedder()
    RunbookSearch(settings, embedder).warm_up()
    assert embedder.documents > 0


def test_unwritable_index_path_is_not_fatal(settings, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    settings.runbook_index_path = blocker / "index.json"
    result = RunbookSearch(settings, FakeEmbedder()).search("mysql", top_k=1)
    assert result.method == "embedding"


# --- Search ---


def test_fake_embedder_finds_the_expected_section(settings):
    result = RunbookSearch(settings, FakeEmbedder()).search("mysql refuses connections", 3)
    assert result.method == "embedding"
    assert result.hits[0][0].section == "Database unreachable"
    scores = [score for _, score in result.hits]
    assert scores == sorted(scores, reverse=True)


def test_min_score_drops_weak_matches(settings):
    result = RunbookSearch(settings, FakeEmbedder()).search("zebra", 3, min_score=0.5)
    assert result.hits == []


def test_keyword_scorer_prefers_rare_words():
    scorer = KeywordScorer(["mysql mysql down", "api down", "grafana panels"])
    scores = scorer.scores("mysql is down")
    assert scores.argmax() == 0
    assert scores[2] == 0


@respx.mock
def test_ollama_embedder_sends_task_prefixes():
    route = respx.post(f"{OLLAMA}/api/embed").mock(
        return_value=httpx.Response(200, json={"embeddings": [[1.0, 0.0]]})
    )
    vectors = OllamaEmbedder(OLLAMA, "nomic-embed-text", 5).embed(["mysql down"], "query")
    assert vectors.shape == (1, 2)
    body = json.loads(route.calls[0].request.content)
    assert body == {"model": "nomic-embed-text", "input": ["search_query: mysql down"]}


@respx.mock
def test_keyword_fallback_when_ollama_is_unreachable(settings):
    respx.post(f"{OLLAMA}/api/embed").mock(side_effect=httpx.ConnectError("refused"))
    search = RunbookSearch(settings, OllamaEmbedder(OLLAMA, "nomic-embed-text", 5))
    search.warm_up()  # logs a warning, does not raise

    result = search.search("grafana log panels empty", 2)
    assert result.method == "keyword"
    assert result.hits[0][0].section == "No logs in Loki"
    assert "ConnectError" in result.note


def test_get_embedder_follows_the_provider(settings):
    assert isinstance(get_embedder(settings), FakeEmbedder)
    settings.llm_provider = "ollama"
    assert isinstance(get_embedder(settings), OllamaEmbedder)


# --- Tool ---


def test_search_runbook_tool_output(settings):
    tools = build_tools(settings)
    output = run_tool(tools, "search_runbook", {"query": "mysql refuses connections", "top_k": 2})
    assert output.startswith('Runbook search for "mysql refuses connections" (embedding):')
    assert "1. [Database unreachable > Symptom] score=" in output
    assert output.count("score=") == 2


@respx.mock
def test_search_runbook_tool_says_when_it_falls_back(settings):
    settings.llm_provider = "ollama"
    respx.post(f"{OLLAMA}/api/embed").mock(return_value=httpx.Response(500))
    output = run_tool(build_tools(settings), "search_runbook", {"query": "loki logs"})
    assert output.startswith("NOTE: keyword fallback, embedding service unavailable")
    assert "[No logs in Loki" in output


def test_search_runbook_tool_errors_are_text(settings):
    tools = build_tools(settings)
    assert run_tool(tools, "search_runbook", {"query": "  "}) == "ERROR: query is empty"
    settings.runbook_path.unlink()
    output = run_tool(tools, "search_runbook", {"query": "mysql"})
    assert output == "ERROR: runbook not readable (FileNotFoundError)"


def test_no_match_lists_the_sections(settings):
    settings.rag_min_score = 0.99
    output = run_tool(build_tools(settings), "search_runbook", {"query": "zebra"})
    assert "No passage matched. Sections: FleetApiDown (critical), Database unreachable" in output


def test_normalized_vectors_give_cosine_similarity(settings):
    search = RunbookSearch(settings, FakeEmbedder())
    search.warm_up()
    assert np.allclose(np.linalg.norm(search.vectors, axis=1), 1.0)


def test_keyword_search_ignores_unknown_words(settings):
    result = RunbookSearch(settings, FakeEmbedder()).keyword_search("zebra loki", 1)
    assert result.method == "keyword"
    assert result.hits[0][0].section == "No logs in Loki"


def test_agent_startup_builds_the_index_in_the_background(settings):
    import threading

    from fastapi.testclient import TestClient

    from agent.llm import FakeProvider
    from agent.main import create_app

    settings.agent_database_url = f"sqlite:///{settings.runbook_path.parent}/agent.db"
    app = create_app(settings, provider=FakeProvider([]), start_worker=True)
    with TestClient(app):
        for thread in threading.enumerate():
            if thread.name == "runbook-index":
                thread.join(timeout=5)
    assert settings.runbook_index_path.exists()
