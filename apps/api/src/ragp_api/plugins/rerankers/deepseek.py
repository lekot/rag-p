"""LLM-based reranker using DeepSeek API.

Sends query + candidates in a single chat request and asks the model
to score relevance.  Falls back to top-k slice on any error.
"""

import asyncio
import json
import logging
import os
from typing import Any, ClassVar

import httpx

from ragp_api.plugins.base import CostEstimate, HealthStatus, Reranker
from ragp_api.plugins.registry import register
from ragp_api.settings import settings

logger = logging.getLogger(__name__)

_RETRY_DELAYS: tuple[float, ...] = (0.5, 1.0, 2.0)

_RERANK_PROMPT = """You are a relevance scoring assistant.
Given a query and a list of documents, score each document from 0 to 1
based on how well it answers the query.  1 = perfectly answers, 0 = irrelevant.

Query: {query}

Documents:
{documents}

Return ONLY a JSON array of scores in the same order as documents:
[0.95, 0.1, 0.7, ...]
No explanations, no markdown."""


@register
class DeepSeekReranker(Reranker):
    name = "deepseek-rerank"
    version = "0.1.0"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "default": "deepseek-v4-flash",
            },
        },
        "required": ["model"],
        "default": {"model": "deepseek-v4-flash"},
    }

    async def rerank(
        self, query: str, candidates: list[dict[str, Any]], top_k: int
    ) -> list[dict[str, Any]]:
        api_key = settings.deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            logger.warning("DeepSeekReranker: no API key configured, falling back to top-k")
            return candidates[:top_k]

        model: str = self.params.get("model", "deepseek-v4-flash")
        base_url = (settings.deepseek_base_url or "https://api.deepseek.com/v1").rstrip("/")
        org_id: str | None = self.params.get("organization_id")
        db = self.params.get("session")

        # Build document list
        doc_list = "\n".join(
            f"[{i}] {c.get('text', '')[:500]}" for i, c in enumerate(candidates[:20])
        )
        prompt = _RERANK_PROMPT.format(query=query, documents=doc_list)

        last_error: Exception | None = None
        for attempt, delay in enumerate(_RETRY_DELAYS):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        f"{base_url}/chat/completions",
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.0,
                            "max_tokens": 500,
                        },
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                    )
                if resp.status_code != 200:
                    last_error = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                    if attempt < len(_RETRY_DELAYS) - 1:
                        await asyncio.sleep(delay)
                    continue

                data = resp.json()
                raw = data["choices"][0]["message"]["content"]
                # Strip markdown fences
                raw = raw.strip()
                if raw.startswith("```"):
                    raw = raw.split("```", 2)[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                    raw = raw.strip()

                scores: list[float] = json.loads(raw)
                if not isinstance(scores, list) or len(scores) != len(candidates[:20]):
                    logger.warning("DeepSeekReranker: unexpected response shape, falling back")
                    return candidates[:top_k]

                # Attach scores and sort
                for i, score in enumerate(scores):
                    if i < len(candidates):
                        candidates[i]["rerank_score"] = float(score)

                candidates.sort(key=lambda c: c.get("rerank_score", 0.0), reverse=True)

                # Track usage
                usage = data.get("usage", {})
                if db is not None and org_id:
                    try:
                        from ragp_api.services.usage import record_usage_event

                        await record_usage_event(
                            db,
                            org_id=org_id,
                            api_key_id=None,
                            pipeline_id=None,
                            model=f"deepseek/{model}",
                            prompt_tokens=int(usage.get("prompt_tokens", 0)),
                            completion_tokens=int(usage.get("completion_tokens", 0)),
                        )
                    except Exception:
                        logger.warning("DeepSeekReranker: failed to record usage", exc_info=True)

                return candidates[:top_k]

            except (json.JSONDecodeError, KeyError, IndexError) as exc:
                last_error = exc
                logger.debug("DeepSeekReranker parse error on attempt %d: %s", attempt + 1, exc)
                if attempt < len(_RETRY_DELAYS) - 1:
                    await asyncio.sleep(delay)
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                last_error = exc
                if attempt < len(_RETRY_DELAYS) - 1:
                    logger.warning(
                        "DeepSeekReranker network error (attempt %d/%d): %s; retrying in %.1fs",
                        attempt + 1,
                        len(_RETRY_DELAYS),
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)

        logger.warning(
            "DeepSeekReranker unavailable after %d attempts (%s); falling back to top-k",
            len(_RETRY_DELAYS),
            last_error,
        )
        return candidates[:top_k]

    async def cost_estimate(self, sample_input: Any) -> CostEstimate:
        return CostEstimate(tokens_in=2000, tokens_out=100, usd=0.001)

    async def health_check(self) -> HealthStatus:
        if not (settings.deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY")):
            return HealthStatus(ok=False, detail="DEEPSEEK_API_KEY not set")
        return HealthStatus(ok=True)
