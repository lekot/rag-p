"""CohereReranker — Cohere rerank API.

Uses an optional outbound HTTP forward proxy (``settings.cohere_http_proxy``)
to route only Cohere SDK calls through the AmneziaWG VPN sidecar
(``cohere-egress``). When the proxy is unset traffic goes direct, preserving
historical behaviour.

Network errors are handled with a small exponential-backoff retry. If all
retries fail the reranker falls back to ``candidates[:top_k]`` — the pipeline
must keep producing answers even when reranking is briefly unavailable.
"""

import asyncio
import contextlib
import logging
from typing import Any, ClassVar

import httpx

from ragp_api.plugins.base import CostEstimate, HealthStatus, Reranker
from ragp_api.plugins.registry import register
from ragp_api.settings import settings

logger = logging.getLogger(__name__)

_RETRY_DELAYS: tuple[float, ...] = (0.5, 1.0, 2.0)


@register
class CohereReranker(Reranker):
    name = "cohere"
    version = "0.1.0"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "default": "rerank-english-v3.0",
                "examples": ["rerank-english-v3.0", "rerank-multilingual-v3.0"],
            },
            "api_key": {"type": "string", "description": "Cohere API key (use env COHERE_API_KEY)"},
        },
        "required": ["model"],
        "default": {"model": "rerank-english-v3.0"},
    }

    async def rerank(
        self, query: str, candidates: list[dict[str, Any]], top_k: int
    ) -> list[dict[str, Any]]:
        try:
            import cohere
        except ImportError:
            # cohere package not installed — skip rerank.
            return candidates[:top_k]

        api_key: str | None = self.params.get("api_key")
        model: str = self.params.get("model", "rerank-english-v3.0")
        proxy_url: str = settings.cohere_http_proxy

        docs = [c.get("text", "") for c in candidates]

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
                client = cohere.AsyncClientV2(**client_kwargs)
                try:
                    response = await client.rerank(
                        model=model,
                        query=query,
                        documents=docs,
                        top_n=top_k,
                    )
                finally:
                    if httpx_client is not None:
                        await httpx_client.aclose()

                reranked: list[dict[str, Any]] = []
                for result in response.results:
                    original = candidates[result.index]
                    reranked.append(
                        {
                            **original,
                            "rerank_score": result.relevance_score,
                        }
                    )
                return reranked
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                last_error = exc
                if httpx_client is not None:
                    with contextlib.suppress(Exception):
                        await httpx_client.aclose()
                if attempt < len(_RETRY_DELAYS) - 1:
                    logger.warning(
                        "cohere reranker network error (attempt %d/%d): %s; retrying in %.1fs",
                        attempt + 1,
                        len(_RETRY_DELAYS),
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                continue

        logger.warning(
            "cohere reranker unavailable after %d attempts (%s); falling back to top-k slice",
            len(_RETRY_DELAYS),
            last_error,
        )
        return candidates[:top_k]

    async def cost_estimate(self, sample_input: Any) -> CostEstimate:
        count = len(sample_input) if isinstance(sample_input, list) else 1
        # Cohere rerank: ~$0.001 per search unit (1 query + up to 100 docs)
        return CostEstimate(usd=count * 0.001, note="estimate: $0.001 per search unit")

    async def health_check(self) -> HealthStatus:
        try:
            import cohere  # noqa: F401

            return HealthStatus(ok=True)
        except ImportError:
            return HealthStatus(ok=False, detail="cohere package not installed")
