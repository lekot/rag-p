from unittest.mock import AsyncMock, patch

import pytest

from ragp_api.plugins.generators.litellm_generator import LiteLLMGenerator
from ragp_api.settings import settings


class _Message:
    content = "DeepSeek answer [1]"


class _Choice:
    message = _Message()


class _Usage:
    prompt_tokens = 11
    completion_tokens = 7


class _CompletionResponse:
    choices = [_Choice()]
    usage = _Usage()


@pytest.mark.asyncio
async def test_litellm_generator_fails_over_from_openai_to_default_model() -> None:
    old_default_model = settings.default_llm_model
    old_deepseek_api_key = settings.deepseek_api_key
    settings.default_llm_model = "deepseek/deepseek-v4-flash"
    settings.deepseek_api_key = "test-deepseek-key"
    try:
        completion = AsyncMock(
            side_effect=[
                RuntimeError("OpenAIException - Country, region, or territory not supported"),
                _CompletionResponse(),
            ]
        )
        generator = LiteLLMGenerator({"model": "openai/gpt-4o-mini"})
        with patch("litellm.acompletion", new=completion):
            result = await generator.generate(
                query="Как сохранить печатную форму в PDF?",
                contexts=[{"text": "Используйте команду сохранения печатной формы в PDF."}],
            )
    finally:
        settings.default_llm_model = old_default_model
        settings.deepseek_api_key = old_deepseek_api_key

    assert result["answer"] == "DeepSeek answer [1]"
    assert result["trace"]["model"] == "deepseek/deepseek-v4-flash"
    assert result["trace"]["fallback_from_model"] == "openai/gpt-4o-mini"
    assert result["trace"]["usage"] == {"prompt_tokens": 11, "completion_tokens": 7}
    assert [call.kwargs["model"] for call in completion.await_args_list] == [
        "openai/gpt-4o-mini",
        "deepseek/deepseek-v4-flash",
    ]


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
