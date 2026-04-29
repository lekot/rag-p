from unittest.mock import AsyncMock, patch

import pytest

from ragp_api.plugins.generators.litellm_generator import LiteLLMGenerator
from ragp_api.settings import settings


@pytest.mark.asyncio
async def test_litellm_generator_extractive_fallback_when_provider_unavailable() -> None:
    old_mode = settings.llm_fallback_mode
    settings.llm_fallback_mode = "extractive"
    try:
        generator = LiteLLMGenerator({"model": "deepseek/deepseek-v4-flash"})
        with patch(
            "litellm.acompletion",
            new=AsyncMock(side_effect=RuntimeError("provider unavailable")),
        ):
            result = await generator.generate(
                query="Как сгруппировать ресурсы?",
                contexts=[
                    {
                        "text": "Ресурсы СКД отчёта группируются по родителю через поле parent.",
                    }
                ],
            )
    finally:
        settings.llm_fallback_mode = old_mode

    assert "LLM сейчас недоступен" in result["answer"]
    assert "поле parent" in result["answer"]
    assert result["trace"]["fallback_mode"] == "extractive"
    assert result["trace"]["usage"] == {"prompt_tokens": 0, "completion_tokens": 0}
