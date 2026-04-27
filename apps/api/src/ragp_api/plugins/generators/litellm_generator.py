"""LiteLLMGenerator — LLM answer generation via LiteLLM."""

from typing import Any, ClassVar, cast

from ragp_api.plugins.base import CostEstimate, Generator, HealthStatus
from ragp_api.plugins.registry import register

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


@register
class LiteLLMGenerator(Generator):
    name = "litellm-generator"
    version = "0.2.0"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "default": "openai/gpt-4o-mini",
                "examples": ["openai/gpt-4o-mini", "openai/gpt-4o", "ollama/llama3"],
            },
            "temperature": {"type": "number", "default": 0.0, "minimum": 0, "maximum": 2},
            "system_prompt": {"type": "string", "default": _DEFAULT_SYSTEM_PROMPT},
            "max_tokens": {"type": "integer", "default": 1024},
        },
        "required": ["model"],
        "default": {
            "model": "openai/gpt-4o-mini",
            "temperature": 0.0,
            "system_prompt": _DEFAULT_SYSTEM_PROMPT,
        },
    }

    async def generate(self, query: str, contexts: list[dict[str, Any]]) -> dict[str, Any]:
        import litellm

        model: str = self.params["model"]
        temperature: float = self.params.get("temperature", 0.0)
        system_prompt: str = self.params.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        max_tokens: int = self.params.get("max_tokens", 1024)

        context_text = "\n\n".join(f"[{i + 1}] {c.get('text', '')}" for i, c in enumerate(contexts))
        user_message = _PROMPT_TEMPLATE.format(query=query, contexts=context_text)

        response = await litellm.acompletion(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # response is untyped in litellm; cast to str to satisfy strict mode
        answer = cast(str, response.choices[0].message.content) or ""
        trace: dict[str, Any] = {
            "model": model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        }
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
