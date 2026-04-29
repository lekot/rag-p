"""Unit tests for BGEReranker — uses mocked CrossEncoder, no real weights."""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from ragp_api.plugins.rerankers import bge as bge_module
from ragp_api.plugins.rerankers.bge import BGEReranker
from ragp_api.plugins.registry import list_plugins


@pytest.fixture(autouse=True)
def clear_model_cache():
    """Reset cached cross-encoder instances so each test sees a fresh load."""
    bge_module._MODEL_CACHE.clear()
    yield
    bge_module._MODEL_CACHE.clear()


@pytest.fixture
def fake_sentence_transformers(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Inject a fake `sentence_transformers` module exposing CrossEncoder mock."""
    cross_encoder_cls = MagicMock(name="CrossEncoder")
    instance = MagicMock(name="CrossEncoderInstance")
    cross_encoder_cls.return_value = instance

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.CrossEncoder = cross_encoder_cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    return cross_encoder_cls


def _candidates() -> list[dict[str, Any]]:
    return [
        {"id": "a", "text": "apple pie recipe"},
        {"id": "b", "text": "rust borrow checker"},
        {"id": "c", "text": "best apple varieties"},
    ]


@pytest.mark.asyncio
async def test_bge_reranker_returns_ordered_by_score(
    fake_sentence_transformers: MagicMock,
) -> None:
    instance = fake_sentence_transformers.return_value
    instance.predict.return_value = [0.9, 0.3, 0.7]

    reranker = BGEReranker(params={"model": "BAAI/bge-reranker-v2-m3"})
    result = await reranker.rerank("apples", _candidates(), top_k=3)

    assert [r["id"] for r in result] == ["a", "c", "b"]
    assert [round(r["rerank_score"], 1) for r in result] == [0.9, 0.7, 0.3]


@pytest.mark.asyncio
async def test_bge_reranker_respects_top_k(
    fake_sentence_transformers: MagicMock,
) -> None:
    instance = fake_sentence_transformers.return_value
    instance.predict.return_value = [0.9, 0.3, 0.7]

    reranker = BGEReranker(params={"model": "BAAI/bge-reranker-v2-m3"})
    result = await reranker.rerank("apples", _candidates(), top_k=2)

    assert len(result) == 2
    assert [r["id"] for r in result] == ["a", "c"]


@pytest.mark.asyncio
async def test_bge_reranker_handles_empty_candidates(
    fake_sentence_transformers: MagicMock,
) -> None:
    reranker = BGEReranker(params={"model": "BAAI/bge-reranker-v2-m3"})
    result = await reranker.rerank("anything", [], top_k=5)

    assert result == []
    # Empty input must not even touch the model.
    fake_sentence_transformers.assert_not_called()


@pytest.mark.asyncio
async def test_bge_reranker_lazy_loads_model_once(
    fake_sentence_transformers: MagicMock,
) -> None:
    instance = fake_sentence_transformers.return_value
    instance.predict.return_value = [0.5, 0.4, 0.3]

    reranker = BGEReranker(params={"model": "BAAI/bge-reranker-v2-m3"})
    await reranker.rerank("q", _candidates(), top_k=3)
    await reranker.rerank("q2", _candidates(), top_k=3)

    # CrossEncoder constructor invoked exactly once across two rerank calls.
    assert fake_sentence_transformers.call_count == 1
    # But the underlying predict has run for each rerank.
    assert instance.predict.call_count == 2


def test_bge_reranker_registered_in_plugin_registry() -> None:
    plugins = list_plugins()
    names = {p["name"] for p in plugins}
    assert "bge-reranker" in names

    bge_entry = next(p for p in plugins if p["name"] == "bge-reranker")
    assert bge_entry["kind"] == "reranker"
    assert "model" in bge_entry["params_schema"]["properties"]
    assert bge_entry["default_params"]["model"] == "BAAI/bge-reranker-v2-m3"
