"""BGEReranker — local cross-encoder reranker (BAAI/bge-reranker-v2-m3).

Designed as a fallback for the Cohere reranker when the Cohere API is
unreachable (e.g. RU IPs are blocked and the AmneziaWG VPN sidecar is the
single point of failure). Runs the cross-encoder model locally on CPU via
``sentence-transformers``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, ClassVar

from ragp_api.plugins.base import CostEstimate, HealthStatus, Reranker
from ragp_api.plugins.registry import register
from ragp_api.settings import settings

logger = logging.getLogger(__name__)

# Module-level cache of loaded cross-encoder instances keyed by model name.
# CrossEncoder weights are heavy (~1.1 GB for bge-reranker-v2-m3); we never
# want to pay that cost more than once per process.
_MODEL_CACHE: dict[str, Any] = {}

_SLOW_RERANK_SECONDS = 5.0


def _load_model(model_name: str, device: str) -> Any:
    """Load (and cache) a CrossEncoder for ``model_name``.

    Raises ``RuntimeError`` if ``sentence-transformers`` is missing or the
    model weights cannot be loaded — we deliberately do not fall back to a
    no-op or random ordering, because that would silently degrade retrieval
    quality.
    """

    cached = _MODEL_CACHE.get(model_name)
    if cached is not None:
        return cached

    try:
        from sentence_transformers import CrossEncoder  # type: ignore[import]
    except ImportError as exc:  # pragma: no cover - import guard
        logger.error("sentence-transformers is not installed: %s", exc)
        raise RuntimeError(
            "BGEReranker requires sentence-transformers. "
            "Install it via `pip install sentence-transformers`."
        ) from exc

    logger.info("Loading BGE reranker model %s on device=%s", model_name, device)
    try:
        model = CrossEncoder(model_name, device=device)
    except Exception as exc:
        logger.error("Failed to load BGE reranker model %s: %s", model_name, exc)
        raise

    _MODEL_CACHE[model_name] = model
    return model


@register
class BGEReranker(Reranker):
    """Local cross-encoder reranker using BAAI/bge-reranker-v2-m3 by default."""

    name = "bge-reranker"
    version = "0.1.0"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "default": "BAAI/bge-reranker-v2-m3",
                "examples": [
                    "BAAI/bge-reranker-v2-m3",
                    "BAAI/bge-reranker-base",
                    "BAAI/bge-reranker-large",
                ],
                "description": "HuggingFace cross-encoder model id.",
            },
            "device": {
                "type": "string",
                "enum": ["cpu", "cuda"],
                "default": "cpu",
                "description": "Torch device to run the cross-encoder on.",
            },
            "max_batch": {
                "type": "integer",
                "minimum": 1,
                "default": 32,
                "description": "Maximum batch size passed to CrossEncoder.predict.",
            },
        },
        "required": ["model"],
        "default": {
            "model": "BAAI/bge-reranker-v2-m3",
            "device": "cpu",
            "max_batch": 32,
        },
    }

    def _resolved_params(self) -> tuple[str, str, int]:
        model = self.params.get("model") or settings.bge_reranker_model
        device = self.params.get("device") or settings.bge_reranker_device
        max_batch = int(self.params.get("max_batch") or settings.bge_reranker_max_batch)
        return model, device, max_batch

    async def rerank(
        self, query: str, candidates: list[dict[str, Any]], top_k: int
    ) -> list[dict[str, Any]]:
        if not candidates:
            return []

        model_name, device, max_batch = self._resolved_params()
        model = _load_model(model_name, device)

        pairs = [(query, c.get("text", "")) for c in candidates]

        start = time.perf_counter()
        # CrossEncoder.predict is synchronous + CPU-heavy — run in a worker
        # thread so we don't block the FastAPI event loop.
        scores = await asyncio.to_thread(
            model.predict,
            pairs,
            batch_size=max_batch,
            show_progress_bar=False,
        )
        elapsed = time.perf_counter() - start
        if elapsed > _SLOW_RERANK_SECONDS:
            logger.warning(
                "BGE rerank slow: %.2fs for %d candidates (model=%s, device=%s)",
                elapsed,
                len(candidates),
                model_name,
                device,
            )

        scored = list(zip(candidates, scores, strict=False))
        scored.sort(key=lambda item: float(item[1]), reverse=True)

        reranked: list[dict[str, Any]] = []
        for candidate, score in scored[:top_k]:
            reranked.append({**candidate, "rerank_score": float(score)})
        return reranked

    async def cost_estimate(self, sample_input: Any) -> CostEstimate:
        # Local inference — no per-request USD cost. Latency is the real cost,
        # but we surface that via metrics, not the cost estimator.
        return CostEstimate(usd=0.0, note="local CPU inference, no API cost")

    async def health_check(self) -> HealthStatus:
        try:
            import sentence_transformers  # type: ignore[import]  # noqa: F401
        except ImportError:
            return HealthStatus(ok=False, detail="sentence-transformers package not installed")

        model_name, _, _ = self._resolved_params()
        if model_name in _MODEL_CACHE:
            return HealthStatus(ok=True, detail=f"model {model_name} loaded")
        return HealthStatus(ok=True, detail=f"model {model_name} not loaded yet (lazy)")
