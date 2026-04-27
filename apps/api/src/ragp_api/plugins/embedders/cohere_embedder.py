"""CohereEmbedder — direct Cohere /v2/embed client (1024-dim v3 family)."""

import os
from typing import Any

from ragp_api.plugins.base import Embedder, CostEstimate, HealthStatus
from ragp_api.plugins.registry import register


_DIMS = {
    "embed-english-v3.0": 1024,
    "embed-multilingual-v3.0": 1024,
    "embed-english-light-v3.0": 384,
    "embed-multilingual-light-v3.0": 384,
}


@register
class CohereEmbedder(Embedder):
    name = "cohere-embedder"
    version = "0.1.0"
    params_schema: dict[str, Any] = {
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

        client = cohere.AsyncClientV2(api_key)
        try:
            response = await client.embed(
                model=self.params["model"],
                texts=texts,
                input_type=self.params.get("input_type", "search_document"),
                embedding_types=["float"],
            )
        finally:
            await client.close()
        return list(response.embeddings.float_)

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
