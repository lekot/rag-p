"""Unit tests for selective cohere routing through the AmneziaWG sidecar.

Verify both plugins:
  * pass an ``httpx_client`` configured with ``proxy=settings.cohere_http_proxy``
    when the setting is non-empty;
  * do **not** pass an ``httpx_client`` when the setting is empty (so the
    cohere SDK keeps its default direct connection);
  * handle network errors per-plugin: the reranker falls back to
    ``candidates[:top_k]`` (graceful), the embedder re-raises (no silent
    vector corruption).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ragp_api.plugins.embedders.cohere_embedder import CohereEmbedder
from ragp_api.plugins.rerankers.cohere import CohereReranker
from ragp_api.settings import settings


@pytest.fixture(autouse=True)
def _reset_cohere_proxy_setting():
    old = settings.cohere_http_proxy
    yield
    settings.cohere_http_proxy = old


def _make_async_context_manager(mock_client: MagicMock) -> MagicMock:
    """Wrap a mock so ``async with cohere.AsyncClientV2(...) as c`` returns it."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


# ---------------------------------------------------------------------------
# Reranker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cohere_reranker_no_proxy_when_setting_empty() -> None:
    settings.cohere_http_proxy = ""

    rerank_response = SimpleNamespace(results=[SimpleNamespace(index=0, relevance_score=0.9)])
    mock_client = MagicMock()
    mock_client.rerank = AsyncMock(return_value=rerank_response)

    fake_module = MagicMock()
    fake_module.AsyncClientV2 = MagicMock(return_value=mock_client)

    reranker = CohereReranker({"model": "rerank-multilingual-v3.0", "api_key": "k"})
    with patch.dict("sys.modules", {"cohere": fake_module}):
        result = await reranker.rerank("q", [{"text": "hello"}], top_k=1)

    assert len(result) == 1
    assert result[0]["rerank_score"] == 0.9
    fake_module.AsyncClientV2.assert_called_once()
    kwargs = fake_module.AsyncClientV2.call_args.kwargs
    assert "httpx_client" not in kwargs
    assert kwargs.get("api_key") == "k"


@pytest.mark.asyncio
async def test_cohere_reranker_uses_proxy_when_setting_set() -> None:
    settings.cohere_http_proxy = "http://cohere-egress:8888"

    rerank_response = SimpleNamespace(results=[SimpleNamespace(index=0, relevance_score=0.42)])
    mock_client = MagicMock()
    mock_client.rerank = AsyncMock(return_value=rerank_response)

    fake_module = MagicMock()
    fake_module.AsyncClientV2 = MagicMock(return_value=mock_client)

    reranker = CohereReranker({"model": "rerank-multilingual-v3.0", "api_key": "k"})
    with patch.dict("sys.modules", {"cohere": fake_module}):
        result = await reranker.rerank("q", [{"text": "hello"}], top_k=1)

    assert result[0]["rerank_score"] == 0.42
    kwargs = fake_module.AsyncClientV2.call_args.kwargs
    httpx_client = kwargs.get("httpx_client")
    assert isinstance(httpx_client, httpx.AsyncClient)
    # httpx 0.28 stores the proxy under _mounts; sniff via transport mount keys.
    mounts = getattr(httpx_client, "_mounts", {})
    proxy_urls = [str(k) for k in mounts]
    assert any("all://" in u or "http" in u for u in proxy_urls), proxy_urls


@pytest.mark.asyncio
async def test_cohere_reranker_falls_back_on_network_error() -> None:
    settings.cohere_http_proxy = "http://cohere-egress:8888"

    mock_client = MagicMock()
    mock_client.rerank = AsyncMock(side_effect=httpx.ConnectError("conn refused"))

    fake_module = MagicMock()
    fake_module.AsyncClientV2 = MagicMock(return_value=mock_client)

    reranker = CohereReranker({"model": "rerank-multilingual-v3.0", "api_key": "k"})
    candidates = [{"text": "a"}, {"text": "b"}, {"text": "c"}]

    # Patch sleep so retries don't slow the test down.
    with (
        patch.dict("sys.modules", {"cohere": fake_module}),
        patch("ragp_api.plugins.rerankers.cohere.asyncio.sleep", new=AsyncMock()),
    ):
        result = await reranker.rerank("q", candidates, top_k=2)

    assert result == candidates[:2]
    # 3 retry attempts -> AsyncClientV2 constructed 3 times.
    assert fake_module.AsyncClientV2.call_count == 3


# ---------------------------------------------------------------------------
# Embedder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cohere_embedder_no_proxy_when_setting_empty(monkeypatch) -> None:
    settings.cohere_http_proxy = ""
    monkeypatch.setenv("COHERE_API_KEY", "k")

    embed_response = SimpleNamespace(embeddings=SimpleNamespace(float_=[[0.1, 0.2, 0.3]]))
    mock_client = MagicMock()
    mock_client.embed = AsyncMock(return_value=embed_response)

    fake_module = MagicMock()
    fake_module.AsyncClientV2 = MagicMock(return_value=_make_async_context_manager(mock_client))

    embedder = CohereEmbedder({"model": "embed-multilingual-v3.0"})
    with patch.dict("sys.modules", {"cohere": fake_module}):
        vectors = await embedder.embed(["hello"])

    assert vectors == [[0.1, 0.2, 0.3]]
    kwargs = fake_module.AsyncClientV2.call_args.kwargs
    assert "httpx_client" not in kwargs


@pytest.mark.asyncio
async def test_cohere_embedder_uses_proxy_when_setting_set(monkeypatch) -> None:
    settings.cohere_http_proxy = "http://cohere-egress:8888"
    monkeypatch.setenv("COHERE_API_KEY", "k")

    embed_response = SimpleNamespace(embeddings=SimpleNamespace(float_=[[0.7]]))
    mock_client = MagicMock()
    mock_client.embed = AsyncMock(return_value=embed_response)

    fake_module = MagicMock()
    fake_module.AsyncClientV2 = MagicMock(return_value=_make_async_context_manager(mock_client))

    embedder = CohereEmbedder({"model": "embed-multilingual-v3.0"})
    with patch.dict("sys.modules", {"cohere": fake_module}):
        vectors = await embedder.embed(["hello"])

    assert vectors == [[0.7]]
    kwargs = fake_module.AsyncClientV2.call_args.kwargs
    httpx_client = kwargs.get("httpx_client")
    assert isinstance(httpx_client, httpx.AsyncClient)


@pytest.mark.asyncio
async def test_cohere_embedder_propagates_network_error(monkeypatch) -> None:
    """Embedder MUST raise on network errors — silent fallback would corrupt
    the vector index with empty/partial embeddings."""
    settings.cohere_http_proxy = "http://cohere-egress:8888"
    monkeypatch.setenv("COHERE_API_KEY", "k")

    mock_client = MagicMock()
    mock_client.embed = AsyncMock(side_effect=httpx.ConnectError("conn refused"))

    fake_module = MagicMock()
    fake_module.AsyncClientV2 = MagicMock(return_value=_make_async_context_manager(mock_client))

    embedder = CohereEmbedder({"model": "embed-multilingual-v3.0"})

    with (
        patch.dict("sys.modules", {"cohere": fake_module}),
        patch("ragp_api.plugins.embedders.cohere_embedder.asyncio.sleep", new=AsyncMock()),
        pytest.raises(httpx.ConnectError),
    ):
        await embedder.embed(["hello"])

    # 3 retries
    assert fake_module.AsyncClientV2.call_count == 3
