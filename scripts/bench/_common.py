"""Shared helpers for benchmark locustfiles.

This module is imported by every locustfile in ``scripts/bench``.  It centralises
environment-variable handling, request headers, and corpus loading so the
individual scenarios stay focused on their workload shape.

The helpers intentionally avoid project-internal imports (``ragp_api`` etc.).
The bench scripts must run from a clean ``pip install -r requirements.txt``
environment without the rest of the monorepo installed.
"""

from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Iterable


CORPUS_DIR = Path(__file__).parent / "sample_docs"


def env_required(name: str) -> str:
    """Return ``os.environ[name]`` or exit with a friendly error.

    Locust loads files at import time, so a missing variable raises
    ``RuntimeError`` immediately and Locust prints the message before any
    workers spin up.
    """

    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "See scripts/bench/README.md for the full list."
        )
    return value


def env_optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip() or default


def api_key_headers(api_key: str) -> dict[str, str]:
    """Return Bearer headers for Public API endpoints (rag/query)."""

    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def session_cookie_header(cookie_value: str) -> dict[str, str]:
    """Return Cookie header for session-authenticated endpoints (datasets, keys)."""

    return {
        "Cookie": f"ragp_session={cookie_value}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def load_corpus(corpus_dir: Path = CORPUS_DIR) -> list[tuple[str, bytes]]:
    """Return ``[(filename, payload), ...]`` from the bundled corpus.

    Files are read once at locust startup so workers do not re-read disk on
    every task.  The corpus is small (~1-2 MB total) so this is safe.
    """

    if not corpus_dir.exists():
        raise RuntimeError(
            f"Corpus directory missing: {corpus_dir}. "
            "Run scripts/bench/seed_dataset.py or restore the bench worktree."
        )

    items: list[tuple[str, bytes]] = []
    for path in sorted(corpus_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in {".txt", ".md"}:
            items.append((path.name, path.read_bytes()))
    if not items:
        raise RuntimeError(f"No .txt/.md files found in {corpus_dir}")
    return items


# Realistic-looking query mix — short / medium / long.  Used by locustfile_query.
DEFAULT_QUERY_MIX: tuple[str, ...] = (
    # short
    "что такое RAG",
    "tariff plans",
    "how does ingestion work",
    "обзор архитектуры",
    "embedding model",
    # medium
    "как именно происходит chunking документов и сколько токенов в одном чанке",
    "what is the difference between dense and hybrid retrieval in this platform",
    "какие лимиты на хранилище и количество запросов в каждом тарифе",
    # long
    (
        "Опиши пожалуйста полный путь обработки одного загруженного PDF: "
        "от парсинга до того момента, когда чанки попадают в pgvector "
        "и становятся доступны через rag/query."
    ),
    (
        "When I run an experiment with three retrievers and two generators, "
        "what is the expected execution order, where are intermediate scores "
        "stored, and how do I export the leaderboard to compare runs later?"
    ),
)


def random_query(rng: random.Random | None = None) -> str:
    rng = rng or random
    return rng.choice(DEFAULT_QUERY_MIX)


def random_top_k(rng: random.Random | None = None) -> int:
    rng = rng or random
    return rng.choice([3, 5, 5, 5, 10, 20])


def chunked(seq: Iterable[bytes], size: int) -> Iterable[bytes]:
    buf: list[bytes] = []
    total = 0
    for item in seq:
        buf.append(item)
        total += len(item)
        if total >= size:
            yield b"".join(buf)
            buf, total = [], 0
    if buf:
        yield b"".join(buf)
