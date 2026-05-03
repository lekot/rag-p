"""LiteLLMEmbedder — OpenAI/Cohere/Ollama embeddings via LiteLLM."""

import os
from typing import Any, ClassVar, cast

from ragp_api.plugins.base import CostEstimate, Embedder, HealthStatus
from ragp_api.plugins.registry import register


@register
class LiteLLMEmbedder(Embedder):
    name = "litellm-embedder"
    version = "0.1.0"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "default": "openai/text-embedding-3-small",
                "examples": [
                    "openai/text-embedding-3-small",
                    "openai/text-embedding-3-large",
                    "ollama/bge-m3",
                    "cohere/embed-english-v3.0",
                ],
            },
            "dim_override": {"type": "integer", "description": "Force embedding dimension"},
        },
        "required": ["model"],
        "default": {"model": "openai/text-embedding-3-small"},
    }

    _dim_cache: int | None = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import litellm

        from ragp_api.settings import settings

        model: str = self.params["model"]
        # litellm ignores the `proxy` kwarg for aembedding, but respects
        # HTTPS_PROXY / HTTP_PROXY env vars.  Set them temporarily so that
        # traffic is routed through the cohere-egress VPN sidecar.
        old_https_proxy = os.environ.get("HTTPS_PROXY")
        old_http_proxy = os.environ.get("HTTP_PROXY")
        if settings.cohere_http_proxy:
            os.environ["HTTPS_PROXY"] = settings.cohere_http_proxy
            os.environ["HTTP_PROXY"] = settings.cohere_http_proxy
        try:
            response = await litellm.aembedding(model=model, input=texts)
        finally:
            if old_https_proxy is not None:
                os.environ["HTTPS_PROXY"] = old_https_proxy
            else:
                os.environ.pop("HTTPS_PROXY", None)
            if old_http_proxy is not None:
                os.environ["HTTP_PROXY"] = old_http_proxy
            else:
                os.environ.pop("HTTP_PROXY", None)
        # response.data is untyped in litellm; each item has an "embedding" list[float]
        embeddings: list[list[float]] = [
            cast(list[float], item["embedding"]) for item in response.data
        ]

        if self._dim_cache is None and embeddings:
            self._dim_cache = len(embeddings[0])

        return embeddings

    @property
    def dim(self) -> int:
        if override := self.params.get("dim_override"):
            return int(override)
        if self._dim_cache is not None:
            return self._dim_cache
        # TODO: query model metadata to determine dimension
        return 1536  # sensible default for text-embedding-3-small

    async def cost_estimate(self, sample_input: Any) -> CostEstimate:
        texts: list[str] = sample_input if isinstance(sample_input, list) else [str(sample_input)]
        total_tokens = sum(len(t.split()) for t in texts)
        # rough estimate: ~$0.02 per 1M tokens for text-embedding-3-small
        usd = total_tokens / 1_000_000 * 0.02
        return CostEstimate(tokens_in=total_tokens, usd=usd)

    async def health_check(self) -> HealthStatus:
        try:
            import litellm  # noqa: F401

            return HealthStatus(ok=True)
        except ImportError:
            return HealthStatus(ok=False, detail="litellm not installed")
