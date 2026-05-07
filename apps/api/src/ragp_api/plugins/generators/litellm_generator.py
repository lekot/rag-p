"""LiteLLMGenerator — LLM answer generation via LiteLLM."""

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, ClassVar, cast

from ragp_api.plugins.base import CostEstimate, Generator, HealthStatus
from ragp_api.plugins.registry import register
from ragp_api.settings import settings

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "deepseek/deepseek-v4-flash"

_DEFAULT_SYSTEM_PROMPT = (
    "You are a strict retrieval-grounded assistant. Rules:\n"
    "1. Answer ONLY using facts from the provided context. NEVER use your prior "
    "training knowledge to fill gaps.\n"
    "2. If the context does not contain the answer, reply exactly: "
    '"В предоставленных источниках ответа нет."\n'
    "3. Every factual claim MUST end with a citation in square brackets pointing "
    "to the source number, e.g. [1] or [2,3]. No claim without a citation.\n"
    "4. Do not infer, guess, or extrapolate beyond what the context literally states.\n"
    "5. If sources contradict, say so explicitly and cite all conflicting sources.\n"
    "6. Answer in the same language as the question."
)

_PROMPT_TEMPLATE = (
    "Question: {query}\n\n"
    "Context (numbered sources — cite by number):\n{contexts}\n\n"
    "Now answer the question using ONLY the context above. "
    'If absent, reply: "В предоставленных источниках ответа нет."'
)


def _uses_proxy_egress(model: str) -> bool:
    return model.startswith(("openai/", "cohere/")) or model.startswith(("gpt-", "o1", "o3", "o4"))


@contextmanager
def _temporary_completion_proxy(model: str) -> Iterator[None]:
    old_https_proxy = os.environ.get("HTTPS_PROXY")
    old_http_proxy = os.environ.get("HTTP_PROXY")
    if settings.cohere_http_proxy and _uses_proxy_egress(model):
        os.environ["HTTPS_PROXY"] = settings.cohere_http_proxy
        os.environ["HTTP_PROXY"] = settings.cohere_http_proxy
    try:
        yield
    finally:
        if old_https_proxy is not None:
            os.environ["HTTPS_PROXY"] = old_https_proxy
        else:
            os.environ.pop("HTTPS_PROXY", None)
        if old_http_proxy is not None:
            os.environ["HTTP_PROXY"] = old_http_proxy
        else:
            os.environ.pop("HTTP_PROXY", None)


def _extractive_answer(query: str, contexts: list[dict[str, Any]]) -> dict[str, Any]:
    if not contexts:
        return {
            "answer": "Не нашёл релевантных чанков для ответа.",
            "trace": {
                "model": "extractive-fallback",
                "fallback_mode": "extractive",
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            },
        }

    snippets = []
    for i, context in enumerate(contexts[:3], start=1):
        text = " ".join(str(context.get("text", "")).split())
        if len(text) > 700:
            text = text[:697].rstrip() + "..."
        snippets.append(f"[{i}] {text}")

    answer = (
        "LLM сейчас недоступен, поэтому показываю извлечённый ответ из найденных "
        f"источников по запросу: {query}\n\n" + "\n\n".join(snippets)
    )
    return {
        "answer": answer,
        "trace": {
            "model": "extractive-fallback",
            "fallback_mode": "extractive",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        },
    }


@register
class LiteLLMGenerator(Generator):
    name = "litellm-generator"
    version = "0.2.0"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "default": _DEFAULT_MODEL,
                "examples": [
                    "deepseek/deepseek-v4-flash",
                    "deepseek/deepseek-chat",
                    "ollama/llama3",
                ],
            },
            "temperature": {"type": "number", "default": 0.0, "minimum": 0, "maximum": 2},
            "system_prompt": {"type": "string", "default": _DEFAULT_SYSTEM_PROMPT},
            "max_tokens": {"type": "integer", "default": 1024},
        },
        "required": ["model"],
        "default": {
            "model": _DEFAULT_MODEL,
            "temperature": 0.0,
            "system_prompt": _DEFAULT_SYSTEM_PROMPT,
        },
    }

    async def generate(self, query: str, contexts: list[dict[str, Any]]) -> dict[str, Any]:
        import os as _os

        import litellm

        # litellm looks for DEEPSEEK_API_KEY in the environment, but we
        # store it via pydantic-settings as RAGP_DEEPSEEK_API_KEY.
        # Forward it so litellm can authenticate.
        if settings.deepseek_api_key and not _os.environ.get("DEEPSEEK_API_KEY"):
            _os.environ["DEEPSEEK_API_KEY"] = settings.deepseek_api_key

        model: str = self.params["model"]
        temperature: float = self.params.get("temperature", 0.0)
        system_prompt: str = self.params.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        max_tokens: int = self.params.get("max_tokens", 1024)

        context_text = "\n\n".join(f"[{i + 1}] {c.get('text', '')}" for i, c in enumerate(contexts))
        user_message = _PROMPT_TEMPLATE.format(query=query, contexts=context_text)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        candidate_models = [model]
        failover_model = settings.default_llm_model
        if (
            failover_model
            and failover_model != model
            and settings.deepseek_api_key
            and failover_model not in candidate_models
        ):
            candidate_models.append(failover_model)

        last_error: Exception | None = None
        fallback_from: str | None = None
        response = None
        used_model = model
        for candidate_model in candidate_models:
            try:
                with _temporary_completion_proxy(candidate_model):
                    response = await litellm.acompletion(
                        model=candidate_model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                used_model = candidate_model
                break
            except Exception as exc:
                last_error = exc
                if candidate_model == model:
                    fallback_from = model
                logger.warning(
                    "LiteLLMGenerator model %s unavailable: %s",
                    candidate_model,
                    str(exc)[:300],
                )
        if response is None:
            if settings.llm_fallback_mode == "extractive":
                return _extractive_answer(query, contexts)
            if last_error is not None:
                raise last_error
            raise RuntimeError("LLM completion failed without an exception")

        # response is untyped in litellm; cast to str to satisfy strict mode
        answer = cast(str, response.choices[0].message.content) or ""
        trace: dict[str, Any] = {
            "model": used_model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        }
        if fallback_from and used_model != fallback_from:
            trace["fallback_from_model"] = fallback_from
        return {"answer": answer, "trace": trace}

    async def cost_estimate(self, sample_input: Any) -> CostEstimate:
        query = (
            str(sample_input)
            if not isinstance(sample_input, dict)
            else sample_input.get("query", "")
        )
        tokens_in = len(query.split()) + 200  # rough estimate including context
        tokens_out = 200
        # ~$0.15 per 1M input tokens for gpt-4o-mini
        usd = (tokens_in * 0.15 + tokens_out * 0.6) / 1_000_000
        return CostEstimate(tokens_in=tokens_in, tokens_out=tokens_out, usd=usd)

    async def health_check(self) -> HealthStatus:
        try:
            import litellm  # noqa: F401

            return HealthStatus(ok=True)
        except ImportError:
            return HealthStatus(ok=False, detail="litellm not installed")
