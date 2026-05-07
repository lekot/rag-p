from typing import Any

import pytest

from ragp_api.services import pipeline_runner


class _Recorder:
    def __init__(self) -> None:
        self.retrieve_calls: list[dict[str, Any]] = []
        self.rerank_calls: list[dict[str, Any]] = []
        self.generator_params: list[dict[str, Any]] = []
        self.generate_calls: list[dict[str, Any]] = []


def _context(index: int) -> dict[str, Any]:
    return {
        "id": f"chunk-{index}",
        "text": f"Section 4.{index} API_LIMIT_{index} contains answer material",
        "score": 1.0,
        "document_id": "doc-1",
        "document_name": "source.md",
    }


@pytest.mark.asyncio
async def test_run_pipeline_expands_retriever_reranker_and_generator_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()

    class FakeRetriever:
        def __init__(self, params: dict[str, Any]) -> None:
            self.params = params

        async def retrieve(
            self,
            query: str,
            top_k: int,
            organization_id: str,
            dataset_id: str | None = None,
            query_vec: list[float] | None = None,
        ) -> list[dict[str, Any]]:
            recorder.retrieve_calls.append(
                {
                    "query": query,
                    "top_k": top_k,
                    "organization_id": organization_id,
                    "dataset_id": dataset_id,
                    "query_vec": query_vec,
                }
            )
            return [_context(i) for i in range(top_k)]

    class FakeReranker:
        def __init__(self, params: dict[str, Any]) -> None:
            self.params = params

        async def rerank(
            self, query: str, candidates: list[dict[str, Any]], top_k: int
        ) -> list[dict[str, Any]]:
            recorder.rerank_calls.append(
                {"query": query, "candidate_count": len(candidates), "top_k": top_k}
            )
            return candidates[:top_k]

    class FakeGenerator:
        def __init__(self, params: dict[str, Any]) -> None:
            recorder.generator_params.append(params)

        async def generate(self, query: str, contexts: list[dict[str, Any]]) -> dict[str, Any]:
            recorder.generate_calls.append({"query": query, "context_count": len(contexts)})
            return {
                "answer": "ok",
                "trace": {"usage": {"prompt_tokens": 11, "completion_tokens": 7}},
            }

    def fake_get_plugin(kind: str, _name: str):
        return {
            "retriever": FakeRetriever,
            "reranker": FakeReranker,
            "generator": FakeGenerator,
        }[kind]

    monkeypatch.setattr(pipeline_runner, "get_plugin", fake_get_plugin)

    result = await pipeline_runner.run_pipeline(
        [
            {
                "plugin_kind": "retriever",
                "plugin_name": "fake-retriever",
                "params": {"top_k": 3, "organization_id": "org-1", "dataset_id": "ds-1"},
            },
            {"plugin_kind": "reranker", "plugin_name": "fake-reranker", "params": {"top_k": 5}},
            {
                "plugin_kind": "generator",
                "plugin_name": "fake-generator",
                "params": {"max_tokens": 128},
            },
        ],
        query="Summarize the whole doc",
        session=object(),
    )

    assert recorder.retrieve_calls[0]["top_k"] == 30
    assert recorder.rerank_calls[0] == {
        "query": "Summarize the whole doc",
        "candidate_count": 30,
        "top_k": 30,
    }
    assert recorder.generator_params[0]["max_tokens"] == 4096
    assert recorder.generate_calls[0]["context_count"] == 30
    assert len(result["contexts"]) == 30


@pytest.mark.asyncio
async def test_run_pipeline_respects_larger_generator_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()

    class FakeGenerator:
        def __init__(self, params: dict[str, Any]) -> None:
            recorder.generator_params.append(params)

        async def generate(self, query: str, contexts: list[dict[str, Any]]) -> dict[str, Any]:
            return {"answer": f"{query}:{len(contexts)}", "trace": {"usage": {}}}

    monkeypatch.setattr(pipeline_runner, "get_plugin", lambda _kind, _name: FakeGenerator)

    await pipeline_runner.run_pipeline(
        [
            {
                "plugin_kind": "generator",
                "plugin_name": "fake-generator",
                "params": {"max_tokens": 8192},
            }
        ],
        query="Q",
        session=object(),
    )

    assert recorder.generator_params[0]["max_tokens"] == 8192


@pytest.mark.asyncio
async def test_run_pipeline_retries_retrieval_and_generation_on_absent_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()

    class FakeRetriever:
        def __init__(self, params: dict[str, Any]) -> None:
            self.params = params

        async def retrieve(
            self,
            query: str,
            top_k: int,
            organization_id: str,
            dataset_id: str | None = None,
            query_vec: list[float] | None = None,
        ) -> list[dict[str, Any]]:
            recorder.retrieve_calls.append(
                {
                    "query": query,
                    "top_k": top_k,
                    "organization_id": organization_id,
                    "dataset_id": dataset_id,
                    "query_vec": query_vec,
                }
            )
            offset = 0 if len(recorder.retrieve_calls) == 1 else 100
            return [_context(offset + i) for i in range(top_k)]

    class FakeGenerator:
        def __init__(self, params: dict[str, Any]) -> None:
            recorder.generator_params.append(params)

        async def generate(self, query: str, contexts: list[dict[str, Any]]) -> dict[str, Any]:
            recorder.generate_calls.append({"query": query, "context_count": len(contexts)})
            if len(recorder.generate_calls) == 1:
                return {
                    "answer": "В предоставленных источниках ответа нет.",
                    "trace": {"usage": {"prompt_tokens": 3, "completion_tokens": 2}},
                }
            return {
                "answer": "answer from retry",
                "trace": {"usage": {"prompt_tokens": 5, "completion_tokens": 4}},
            }

    def fake_get_plugin(kind: str, _name: str):
        return {"retriever": FakeRetriever, "generator": FakeGenerator}[kind]

    monkeypatch.setattr(pipeline_runner, "get_plugin", fake_get_plugin)

    result = await pipeline_runner.run_pipeline(
        [
            {
                "plugin_kind": "retriever",
                "plugin_name": "fake-retriever",
                "params": {"top_k": 5, "organization_id": "org-1"},
            },
            {"plugin_kind": "generator", "plugin_name": "fake-generator", "params": {}},
        ],
        query="What changed?",
        session=object(),
    )

    assert result["answer"] == "answer from retry"
    assert len(recorder.retrieve_calls) == 2
    assert recorder.retrieve_calls[0]["top_k"] == 30
    assert recorder.retrieve_calls[1]["top_k"] == 30
    assert recorder.retrieve_calls[1]["query"].startswith("What changed?\n\nRelated exact terms:")
    assert len(recorder.generate_calls) == 2
    assert recorder.generate_calls[1] == {"query": "What changed?", "context_count": 60}
    assert result["usage"] == {"prompt_tokens": 8, "completion_tokens": 6}
    assert any(
        trace.get("trace", {}).get("retried")
        for trace in result["traces"]
        if trace["kind"] == "generator"
    )
