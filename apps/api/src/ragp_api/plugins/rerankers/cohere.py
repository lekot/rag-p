"""CohereReranker — Cohere rerank API."""

from typing import Any, ClassVar

from ragp_api.plugins.base import CostEstimate, HealthStatus, Reranker
from ragp_api.plugins.registry import register


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

            api_key: str | None = self.params.get("api_key")
            model: str = self.params.get("model", "rerank-english-v3.0")

            client = cohere.AsyncClientV2(api_key=api_key)
            docs = [c.get("text", "") for c in candidates]

            response = await client.rerank(
                model=model,
                query=query,
                documents=docs,
                top_n=top_k,
            )
            reranked = []
            for result in response.results:
                original = candidates[result.index]
                reranked.append(
                    {
                        **original,
                        "rerank_score": result.relevance_score,
                    }
                )
            return reranked
        except ImportError:
            # TODO: install cohere package
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
