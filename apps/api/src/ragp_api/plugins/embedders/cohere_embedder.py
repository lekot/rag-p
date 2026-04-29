"""CohereEmbedder — direct Cohere /v2/embed client (1024-dim v3 family).

Uses an optional outbound HTTP forward proxy (``settings.cohere_http_proxy``)
to route only Cohere SDK calls through the AmneziaWG VPN sidecar
(``cohere-egress``). When the proxy is unset traffic goes direct.

Unlike the reranker, the embedder MUST NOT silently fall back on a network
error: returning empty/partial vectors would corrupt the index. We retry with
exponential backoff and re-raise the underlying network error if all attempts
fail — the caller is expected to surface the failure to the user / job queue.
"""

import asyncio
import contextlib
import logging
import os
from typing import Any, ClassVar

import httpx

from ragp_api.plugins.base import CostEstimate, Embedder, HealthStatus
from ragp_api.plugins.registry import register
from ragp_api.settings import settings

logger = logging.getLogger(__name__)

_DIMS = {
    "embed-english-v3.0": 1024,
    "embed-multilingual-v3.0": 1024,
    "embed-english-light-v3.0": 384,
    "embed-multilingual-light-v3.0": 384,
}

_RETRY_DELAYS: tuple[float, ...] = (0.5, 1.0, 2.0)


@register
class CohereEmbedder(Embedder):
    name = "cohere-embedder"
    version = "0.1.0"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "default": "embed-multilingual-v3.0",
                "examples": list(_DIMS.keys()),
            },
            "input_type": {
                "type": "string",
                "default": "search_document",
                "enum": ["search_document", "search_query", "classification", "clustering"],
            },
        },
        "required": ["model"],
        "default": {"model": "embed-multilingual-v3.0", "input_type": "search_document"},
    }

    async def embed(self, texts: list[str]) -> list[list[float]]:
        api_key = os.environ.get("COHERE_API_KEY")
        if not api_key:
            raise RuntimeError("COHERE_API_KEY env var not set")

        import cohere

        proxy_url: str = settings.cohere_http_proxy
        model = self.params["model"]
        input_type = self.params.get("input_type", "search_document")

        last_error: Exception | None = None
        for attempt, delay in enumerate(_RETRY_DELAYS):
            httpx_client: httpx.AsyncClient | None = None
            if proxy_url:
                httpx_client = httpx.AsyncClient(
                    proxy=proxy_url,
                    timeout=httpx.Timeout(15.0, connect=5.0),
                )
            try:
                client_kwargs: dict[str, Any] = {"api_key": api_key}
                if httpx_client is not None:
                    client_kwargs["httpx_client"] = httpx_client
                async with cohere.AsyncClientV2(**client_kwargs) as client:
                    response = await client.embed(
                        model=model,
                        texts=texts,
                        input_type=input_type,
                        embedding_types=["float"],
                    )
                # float_ is Optional[list[list[float]]]; embedding_types=["float"] guarantees set.
                return list(response.embeddings.float_ or [])
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                last_error = exc
                if attempt < len(_RETRY_DELAYS) - 1:
                    logger.warning(
                        "cohere embedder network error (attempt %d/%d): %s; retrying in %.1fs",
                        attempt + 1,
                        len(_RETRY_DELAYS),
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                continue
            finally:
                if httpx_client is not None:
                    with contextlib.suppress(Exception):
                        await httpx_client.aclose()

        # All retries exhausted — re-raise. Silent fallback is not safe for
        # embeddings (would corrupt the vector index).
        assert last_error is not None
        raise last_error

    @property
    def dim(self) -> int:
        return _DIMS.get(self.params["model"], 1024)

    async def cost_estimate(self, sample_input: Any) -> CostEstimate:
        texts: list[str] = sample_input if isinstance(sample_input, list) else [str(sample_input)]
        # Cohere counts characters; rough: 4 chars per token
        total_tokens = sum(len(t) for t in texts) // 4
        # embed-v3 is $0.10 / 1M tokens
        usd = total_tokens / 1_000_000 * 0.10
        return CostEstimate(tokens_in=total_tokens, usd=usd)

    async def health_check(self) -> HealthStatus:
        if not os.environ.get("COHERE_API_KEY"):
            return HealthStatus(ok=False, detail="COHERE_API_KEY not set")
        try:
            import cohere  # noqa: F401

            return HealthStatus(ok=True)
        except ImportError:
            return HealthStatus(ok=False, detail="cohere package not installed")
