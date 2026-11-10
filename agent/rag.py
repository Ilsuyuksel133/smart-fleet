"""Retrieval over the runbook: find the passages that answer a free-text question.

get_runbook (agent/tools.py) returns a whole section when the alert name is
known. search_runbook, built on this module, answers everything else
("no logs in Loki", "database unreachable") by meaning instead of by title:

1. Chunking: the runbook is split at its "## " headings; long sections are
   split further between paragraphs. Code blocks are never cut in half.
2. Embedding: every chunk becomes a vector (nomic-embed-text through Ollama).
3. Search: the question is embedded too, and the chunks with the highest
   cosine similarity are returned.

The runbook has about 30 chunks, so the vectors are a small numpy array in
memory, cached in a JSON file. A vector database would only pay off with many
thousands of chunks (then sqlite-vec or pgvector).

If the embedding service is unavailable, the search falls back to keyword
matching (BM25) and says so, like the other tools: no exception, readable text.
"""

import hashlib
import json
import logging
import math
import re
import threading
import zlib
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import httpx
import numpy as np

from agent.config import Settings

log = logging.getLogger("fleet-agent")

Kind = Literal["document", "query"]


# --- Chunking ---


@dataclass(frozen=True)
class Chunk:
    id: str  # e.g. "database-unreachable-2"
    section: str  # the "## " heading, e.g. "Database unreachable"
    heading_path: str  # where in the section, e.g. "Database unreachable > Checks"
    text: str

    def embedding_text(self) -> str:
        # The heading gives a short passage its context ("Checks" of what?)
        return f"{self.heading_path}\n{self.text}"


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def split_sections(text: str) -> list[tuple[str, str]]:
    """(title, body) per "## " heading. Lines inside code blocks are never headings."""
    sections: list[tuple[str, list[str]]] = []
    in_code = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        if not in_code and line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif sections:  # the text before the first section is only an introduction
            sections[-1][1].append(line)
    return [(title, "\n".join(lines).strip()) for title, lines in sections]


def split_blocks(body: str) -> list[str]:
    """Paragraphs separated by blank lines; a code block always stays in one piece."""
    blocks, current, in_code = [], [], False
    for line in body.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        if not line.strip() and not in_code:
            if current:
                blocks.append("\n".join(current))
                current = []
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    # "---" only separates sections visually
    return [block for block in blocks if block.strip() != "---"]


def block_label(block: str) -> str | None:
    """The sub-heading a block starts with: "**Checks**" or "### Checks"."""
    first = block.splitlines()[0].strip()
    match = re.fullmatch(r"\*\*(.+?)\*\*|###\s+(.+)", first)
    return (match.group(1) or match.group(2)).strip() if match else None


def chunk_runbook(text: str, max_chars: int = 800) -> list[Chunk]:
    chunks = []
    for title, body in split_sections(text):
        if len(body) <= max_chars:
            groups = [[body]]
        else:
            # Pack paragraphs into chunks of at most max_chars. A single block that is
            # longer (a big code block) becomes a chunk of its own instead of being cut.
            groups, current, size = [], [], 0
            for block in split_blocks(body):
                if current and size + len(block) > max_chars:
                    groups.append(current)
                    current, size = [], 0
                current.append(block)
                size += len(block) + 2
            if current:
                groups.append(current)

        for number, group in enumerate(groups, start=1):
            labels = [label for block in group if (label := block_label(block))]
            path = f"{title} > {', '.join(labels)}" if labels and len(groups) > 1 else title
            chunks.append(
                Chunk(
                    id=f"{slugify(title)}-{number}",
                    section=title,
                    heading_path=path,
                    text="\n\n".join(group),
                )
            )
    return chunks


# --- Embedding ---


class Embedder(ABC):
    """Turns texts into vectors. Documents and queries may be embedded differently."""

    name: str

    @abstractmethod
    def embed(self, texts: list[str], kind: Kind) -> np.ndarray:
        """One row per text."""


class OllamaEmbedder(Embedder):
    # nomic-embed-text was trained with these task prefixes and works best with them
    PREFIXES = {"document": "search_document: ", "query": "search_query: "}

    def __init__(self, base_url: str, model: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.name = f"ollama/{model}"

    def embed(self, texts: list[str], kind: Kind) -> np.ndarray:
        response = httpx.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": [self.PREFIXES[kind] + t for t in texts]},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return np.asarray(response.json()["embeddings"], dtype=np.float32)


class FakeEmbedder(Embedder):
    """Deterministic vectors from word hashes, for tests and CI (no model needed).

    Texts that share words get similar vectors, so a search still finds sensible
    passages, but synonyms ("down" vs "unreachable") are not understood.
    """

    name = "fake"

    def __init__(self, dimensions: int = 256):
        self.dimensions = dimensions

    def embed(self, texts: list[str], kind: Kind) -> np.ndarray:
        vectors = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in tokenize(text):
                # crc32, not hash(): Python's string hash changes between processes
                vectors[row, zlib.crc32(word.encode()) % self.dimensions] += 1.0
        return vectors


def get_embedder(settings: Settings) -> Embedder:
    if settings.llm_provider == "fake":
        return FakeEmbedder()
    return OllamaEmbedder(
        settings.ollama_url, settings.embedding_model, settings.tool_timeout_seconds
    )


def normalize(vectors: np.ndarray) -> np.ndarray:
    """Unit-length rows, so that a dot product is the cosine similarity."""
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return vectors / np.where(norms == 0, 1.0, norms)


# --- Keyword fallback (BM25) ---

STOPWORDS = frozenset(
    "a an and are as at be but by can do does for from how i if in is it its my no not "
    "of on or so the there this to was what when where which who why will with".split()
)


def tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9_]+", text.lower()) if w not in STOPWORDS]


class KeywordScorer:
    """BM25: rewards query words that are rare in the runbook but frequent in a chunk."""

    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75):
        self.docs = [Counter(tokenize(doc)) for doc in documents]
        self.lengths = [sum(doc.values()) for doc in self.docs]
        self.avg_length = sum(self.lengths) / max(len(self.docs), 1)
        frequency = Counter(word for doc in self.docs for word in doc)
        total = len(self.docs)
        self.idf = {w: math.log(1 + (total - n + 0.5) / (n + 0.5)) for w, n in frequency.items()}
        self.k1, self.b = k1, b

    def scores(self, query: str) -> np.ndarray:
        result = np.zeros(len(self.docs))
        for word in set(tokenize(query)):
            idf = self.idf.get(word)
            if idf is None:
                continue
            for i, doc in enumerate(self.docs):
                tf = doc[word]
                if tf:
                    norm = self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avg_length)
                    result[i] += idf * tf * (self.k1 + 1) / (tf + norm)
        return result


# --- Index and search ---


@dataclass
class SearchResult:
    method: Literal["embedding", "keyword"]
    hits: list[tuple[Chunk, float]]  # best first
    note: str = ""  # why the keyword fallback was used


class RunbookSearch:
    """Chunks, vectors and both scorers for the runbook; rebuilt when the file changes."""

    def __init__(self, settings: Settings, embedder: Embedder):
        self.settings = settings
        self.embedder = embedder
        self.lock = threading.Lock()
        self.runbook_sha = ""
        self.chunks: list[Chunk] = []
        self.keyword: KeywordScorer | None = None
        self.vectors: np.ndarray | None = None

    def _refresh(self) -> None:
        """Re-read the runbook; start over if its content changed."""
        text = Path(self.settings.runbook_path).read_text(encoding="utf-8")
        sha = hashlib.sha256(text.encode()).hexdigest()
        if sha != self.runbook_sha:
            self.runbook_sha = sha
            self.chunks = chunk_runbook(text, self.settings.rag_chunk_chars)
            self.keyword = KeywordScorer([chunk.embedding_text() for chunk in self.chunks])
            self.vectors = None

    def _cache_key(self) -> dict:
        return {
            "runbook_sha256": self.runbook_sha,
            "embedder": self.embedder.name,
            "chunk_chars": self.settings.rag_chunk_chars,
        }

    def _load_cached_vectors(self) -> np.ndarray | None:
        path = Path(self.settings.runbook_index_path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if data.get("key") != self._cache_key():
            return None
        return np.asarray(data["vectors"], dtype=np.float32)

    def _save_vectors(self, vectors: np.ndarray) -> None:
        path = Path(self.settings.runbook_index_path)
        data = {
            "key": self._cache_key(),
            # Stored for people reading the file; the chunks are always recomputed
            "chunks": [asdict(chunk) for chunk in self.chunks],
            "vectors": vectors.round(6).tolist(),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
        except OSError as error:
            # Not fatal: the index is rebuilt at the next start
            log.warning("runbook index not saved", extra={"error": str(error)})

    def _ensure_vectors(self) -> np.ndarray:
        """Vectors of the current chunks: from memory, from the cache file, or computed."""
        with self.lock:
            self._refresh()
            if self.vectors is None:
                cached = self._load_cached_vectors()
                if cached is not None and len(cached) == len(self.chunks):
                    self.vectors = cached
                    log.info("runbook index loaded", extra={"chunks": len(self.chunks)})
                else:
                    texts = [chunk.embedding_text() for chunk in self.chunks]
                    self.vectors = normalize(self.embedder.embed(texts, "document"))
                    self._save_vectors(self.vectors)
                    log.info(
                        "runbook index built",
                        extra={"chunks": len(self.chunks), "embedder": self.embedder.name},
                    )
            return self.vectors

    def warm_up(self) -> None:
        """Build or load the index ahead of the first search (agent startup)."""
        try:
            self._ensure_vectors()
        except Exception as error:
            log.warning("runbook index not built", extra={"error": f"{type(error).__name__}"})

    def search(self, query: str, top_k: int, min_score: float = 0.0) -> SearchResult:
        """Semantic search; keyword search if the embedding service fails. Raises only
        if the runbook itself cannot be read."""
        try:
            vectors = self._ensure_vectors()
            query_vector = normalize(self.embedder.embed([query], "query"))[0]
        except Exception as error:
            with self.lock:
                self._refresh()
                scores = self.keyword.scores(query)
            return SearchResult(
                method="keyword",
                hits=self._top(scores, top_k, min_score=1e-9),
                note=f"embedding service unavailable ({type(error).__name__})",
            )
        return SearchResult(
            method="embedding", hits=self._top(vectors @ query_vector, top_k, min_score)
        )

    def keyword_search(self, query: str, top_k: int) -> SearchResult:
        with self.lock:
            self._refresh()
            scores = self.keyword.scores(query)
        return SearchResult(method="keyword", hits=self._top(scores, top_k, min_score=1e-9))

    def _top(self, scores: np.ndarray, top_k: int, min_score: float) -> list[tuple[Chunk, float]]:
        order = np.argsort(-scores, kind="stable")[:top_k]
        return [(self.chunks[i], float(scores[i])) for i in order if scores[i] >= min_score]

    def section_titles(self) -> list[str]:
        return list(dict.fromkeys(chunk.section for chunk in self.chunks))


def format_results(query: str, result: SearchResult, titles: list[str]) -> str:
    """The text the model sees: passages with their place in the runbook and a score."""
    lines = []
    if result.method == "keyword":
        lines.append(f"NOTE: keyword fallback, {result.note}. Scores are BM25, not similarity.")
    lines.append(f'Runbook search for "{query}" ({result.method}):')
    if not result.hits:
        lines.append("No passage matched. Sections: " + ", ".join(titles))
    for rank, (chunk, score) in enumerate(result.hits, start=1):
        lines.append(f"\n{rank}. [{chunk.heading_path}] score={score:.2f}\n{chunk.text}")
    return "\n".join(lines)
