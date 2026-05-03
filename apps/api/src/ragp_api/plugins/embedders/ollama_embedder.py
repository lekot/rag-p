"""OllamaEmbedder — embeddings via local Ollama HTTP API."""

import logging
import os
from typing import Any, ClassVar

import httpx

from ragp_api.plugins.base import CostEstimate, Embedder, HealthStatus
from ragp_api.plugins.registry import register

_DEFAULT_DIMS = {
    "bge-m3": 1024,
    "bge-large": 1024,
    "bge-large-en": 1024,
    "bge-large-en-v1.5": 1024,
    "nomic-embed-text": 768,
    "nomic-embed-text:v1.5": 768,
    "mxbai-embed-large": 1024,
}


def _resolve_dim(model: str) -> int:
    base = model.split(":")[0]
    return _DEFAULT_DIMS.get(model) or _DEFAULT_DIMS.get(base) or 1024


@register
class OllamaEmbedder(Embedder):
    name = "ollama-embedder"
    version = "0.1.0"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "default": "bge-m3",
                "examples": list(_DEFAULT_DIMS.keys()),
            },
            "host": {
                "type": "string",
                "description": "Override OLLAMA_HOST (default: http://rag-p-ollama:11434)",
            },
        },
        "required": ["model"],
        "default": {"model": "bge-m3"},
    }

    def _host(self) -> str:
        return (
            self.params.get("host") or os.environ.get("OLLAMA_HOST") or "http://rag-p-ollama:11434"
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        host = self._host()
        model: str = self.params["model"]
        # Use Ollama batch API (/api/embed) with groups of 50 texts.
        # Sending all texts at once overwhelms Ollama (500 error).
        # Falls back to per-text /api/embeddings for older Ollama versions.
        batch_size = 50
        all_vectors: list[list[float]] = [None] * len(texts)  # type: ignore[assignment]
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            for batch_start in range(0, len(texts), batch_size):
                batch = texts[batch_start : batch_start + batch_size]
                try:
                    resp = await client.post(
                        f"{host}/api/embed",
                        json={"model": model, "input": batch},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    vectors = data.get("embeddings") or []
                    if len(vectors) != len(batch):
                        raise RuntimeError(
                            f"ollama returned {len(vectors)} embeddings, expected {len(batch)}"
                        )
                    for i, v in enumerate(vectors):
                        all_vectors[batch_start + i] = list(v)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 404:
                        raise
                    # Fallback: older Ollama without /api/embed
                    logger = logging.getLogger(__name__)
                    logger.warning(
                        "Ollama /api/embed not available (404), falling back to /api/embeddings"
                    )
                    for i, t in enumerate(batch):
                        resp = await client.post(
                            f"{host}/api/embeddings",
                            json={"model": model, "prompt": t},
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        vec = data.get("embedding") or (data.get("embeddings") or [None])[0]
                        if vec is None:
                            raise RuntimeError(f"ollama returned no embedding for text len={len(t)}")
                        all_vectors[batch_start + i] = list(vec)
        return all_vectors  # type: ignore[return-value]

    @property
    def dim(self) -> int:
        return _resolve_dim(self.params["model"])

    async def cost_estimate(self, sample_input: Any) -> CostEstimate:
        texts: list[str] = sample_input if isinstance(sample_input, list) else [str(sample_input)]
        total_tokens = sum(len(t) for t in texts) // 4
        return CostEstimate(tokens_in=total_tokens, usd=0.0, note="self-hosted")

    async def health_check(self) -> HealthStatus:
        host = self._host()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                r = await client.get(f"{host}/")
            return HealthStatus(ok=r.status_code == 200, detail=f"{host}: {r.status_code}")
        except Exception as e:
            return HealthStatus(ok=False, detail=str(e))
