"""Executes a pipeline on a single query."""

import re
from contextlib import suppress
from typing import Any, cast

from ragp_api.plugins.base import Embedder, Generator, Reranker, Retriever
from ragp_api.plugins.registry import get_plugin

_RAG_MIN_CONTEXT_TOP_K = 30
_RAG_MAX_CONTEXT_TOP_K = 60
_RAG_MIN_GENERATOR_MAX_TOKENS = 4096
_ANSWER_ABSENT_PHRASES = (
    "В предоставленных источниках ответа нет.",
    "в предоставленных источниках ответа нет",
)
_RAG_RETRY_FALLBACK_TERMS = (
    "table",
    "section",
    "clause",
    "number",
    "date",
    "appendix",
    "definition",
    "requirement",
)


def _effective_context_top_k(requested_top_k: Any) -> int:
    try:
        top_k = int(requested_top_k)
    except (TypeError, ValueError):
        top_k = 10
    return min(max(top_k, _RAG_MIN_CONTEXT_TOP_K), _RAG_MAX_CONTEXT_TOP_K)


def _apply_generator_budget_floor(params: dict[str, Any]) -> None:
    try:
        requested_max_tokens = int(params.get("max_tokens", _RAG_MIN_GENERATOR_MAX_TOKENS))
    except (TypeError, ValueError):
        requested_max_tokens = _RAG_MIN_GENERATOR_MAX_TOKENS
    params["max_tokens"] = max(requested_max_tokens, _RAG_MIN_GENERATOR_MAX_TOKENS)


def _is_absent_answer(answer: str) -> bool:
    normalized = " ".join(answer.strip().casefold().split())
    if not normalized:
        return True
    return any(
        phrase.casefold().rstrip(".") in normalized.rstrip(".") for phrase in _ANSWER_ABSENT_PHRASES
    )


def _build_retry_query(query: str, contexts: list[dict[str, Any]]) -> str:
    query_terms = {term.casefold() for term in re.findall(r"\w+", query)}
    retry_terms: list[str] = []
    seen_retry_terms: set[str] = set()

    for context in contexts[:8]:
        text = str(context.get("text", ""))
        candidates = re.findall(r"\b\d+(?:\.\d+)+\b|\b[A-ZА-ЯЁ]{2,}\b|\b[\w-]{5,}\b", text)
        for candidate in candidates:
            normalized = candidate.casefold()
            if normalized in query_terms or normalized in seen_retry_terms:
                continue
            seen_retry_terms.add(normalized)
            retry_terms.append(candidate)
            if len(retry_terms) >= 24:
                break
        if len(retry_terms) >= 24:
            break

    if not retry_terms:
        retry_terms = list(_RAG_RETRY_FALLBACK_TERMS)

    return f"{query}\n\nRelated exact terms: {' '.join(retry_terms)}"


def _merge_contexts_by_id(
    contexts: list[dict[str, Any]],
    extra_contexts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for context in contexts + extra_contexts:
        key = str(
            context.get("id") or f"{context.get('document_id', '')}:{context.get('text', '')}"
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(context)
    return merged


def _usage_from_generation_result(result: dict[str, Any]) -> dict[str, int]:
    trace: dict[str, Any] = result.get("trace", {})
    usage_raw: dict[str, Any] = trace.get("usage", {})
    return {
        "prompt_tokens": int(usage_raw.get("prompt_tokens", 0)),
        "completion_tokens": int(usage_raw.get("completion_tokens", 0)),
    }


async def run_pipeline(nodes: list[dict[str, Any]], query: str, session: Any) -> dict[str, Any]:
    """Execute pipeline nodes in sequence: embed -> retrieve -> rerank -> generate."""
    contexts: list[dict[str, Any]] = []
    answer: str = ""
    traces: list[dict[str, Any]] = []

    # Phase 1: embed query (so retriever gets a query_vec for vector search)
    query_vec: list[float] | None = None
    embedder: Embedder | None = None
    for node in nodes:
        if node.get("plugin_kind") != "embedder":
            continue
        name: str = node["plugin_name"]
        params: dict[str, Any] = dict(node.get("params", {}))
        cls = get_plugin("embedder", name)
        if cls is None:
            traces.append({"kind": "embedder", "name": name, "error": "not found"})
            continue
        try:
            embedder = cast(Embedder, cls(params))
            query_vec = (await embedder.embed([query]))[0]
            traces.append({"kind": "embedder", "name": name, "embedded": True})
            break  # use first working embedder
        except Exception as exc:
            traces.append({"kind": "embedder", "name": name, "error": str(exc)[:100]})

    # Phase 2: execute remaining nodes in order
    context_nodes_seen: list[dict[str, Any]] = []

    async def execute_context_node(
        node: dict[str, Any],
        node_query: str,
        node_query_vec: list[float] | None,
        current_contexts: list[dict[str, Any]],
        *,
        append_trace: bool,
        retry: bool = False,
    ) -> list[dict[str, Any]]:
        kind: str = node["plugin_kind"]
        name = node["plugin_name"]
        params = dict(node.get("params", {}))

        cls = get_plugin(kind, name)
        if cls is None:
            raise ValueError(f"Plugin {kind}/{name} not found")

        if kind == "retriever":
            params["session"] = session
            retriever = cast(Retriever, cls(params))
            top_k = _effective_context_top_k(params.get("top_k", 10))
            next_contexts = await retriever.retrieve(
                query=node_query,
                top_k=top_k,
                organization_id=params.get("organization_id", ""),
                dataset_id=params.get("dataset_id"),
                query_vec=node_query_vec,
            )
            if append_trace:
                traces.append(
                    {
                        "kind": kind,
                        "name": name,
                        "contexts_count": len(next_contexts),
                        "top_k": top_k,
                        **({"retry": True} if retry else {}),
                    }
                )
            return next_contexts

        if kind == "reranker":
            params["session"] = session
            reranker = cast(Reranker, cls(params))
            top_k = _effective_context_top_k(params.get("top_k", 10))
            next_contexts = await reranker.rerank(
                query=node_query, candidates=current_contexts, top_k=top_k
            )
            if append_trace:
                traces.append(
                    {
                        "kind": kind,
                        "name": name,
                        "reranked_count": len(next_contexts),
                        "top_k": top_k,
                        **({"retry": True} if retry else {}),
                    }
                )
            return next_contexts

        return current_contexts

    async def rerun_context_nodes(
        retry_query: str, retry_query_vec: list[float] | None
    ) -> list[dict[str, Any]]:
        retry_contexts: list[dict[str, Any]] = []
        for seen_node in context_nodes_seen:
            retry_contexts = await execute_context_node(
                seen_node,
                retry_query,
                retry_query_vec,
                retry_contexts,
                append_trace=True,
                retry=True,
            )
        return retry_contexts

    for node in nodes:
        kind: str = node["plugin_kind"]
        name = node["plugin_name"]
        params = dict(node.get("params", {}))

        cls = get_plugin(kind, name)
        if cls is None:
            raise ValueError(f"Plugin {kind}/{name} not found")

        if kind in {"retriever", "reranker"}:
            context_nodes_seen.append(node)
            contexts = await execute_context_node(
                node, query, query_vec, contexts, append_trace=True
            )

        elif kind == "generator":
            params["session"] = session
            _apply_generator_budget_floor(params)
            generator = cast(Generator, cls(params))
            result = await generator.generate(query=query, contexts=contexts)
            answer = result.get("answer", "")
            gen_trace = result.get("trace", {})
            if _is_absent_answer(answer) and context_nodes_seen:
                retry_query = _build_retry_query(query, contexts)
                retry_query_vec = query_vec
                if embedder is not None:
                    with suppress(Exception):
                        retry_query_vec = (await embedder.embed([retry_query]))[0]
                retry_contexts = await rerun_context_nodes(retry_query, retry_query_vec)
                merged_contexts = _merge_contexts_by_id(contexts, retry_contexts)
                if merged_contexts:
                    retry_result = await generator.generate(query=query, contexts=merged_contexts)
                    retry_answer = retry_result.get("answer", "")
                    retry_trace = retry_result.get("trace", {})
                    usage = _usage_from_generation_result(result)
                    retry_usage = _usage_from_generation_result(retry_result)
                    gen_trace = {
                        **retry_trace,
                        "usage": {
                            "prompt_tokens": usage["prompt_tokens"] + retry_usage["prompt_tokens"],
                            "completion_tokens": usage["completion_tokens"]
                            + retry_usage["completion_tokens"],
                        },
                        "retried": True,
                    }
                    contexts = merged_contexts
                    if not _is_absent_answer(retry_answer):
                        answer = retry_answer
            traces.append({"kind": kind, "name": name, "trace": gen_trace})

        elif kind == "chunker":
            traces.append({"kind": kind, "name": name, "skipped": "ingest-only"})

        elif kind == "embedder":
            pass  # already handled in Phase 1

    # Aggregate token usage from all generator traces
    prompt_tokens = 0
    completion_tokens = 0
    for t in traces:
        if t.get("kind") == "generator":
            u = t.get("trace", {}).get("usage", {})
            prompt_tokens += int(u.get("prompt_tokens", 0))
            completion_tokens += int(u.get("completion_tokens", 0))

    return {
        "answer": answer,
        "contexts": contexts,
        "traces": traces,
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }
