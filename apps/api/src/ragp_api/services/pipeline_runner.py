"""Executes a pipeline on a single query."""

from typing import Any, cast

from ragp_api.plugins.base import Embedder, Generator, Reranker, Retriever
from ragp_api.plugins.registry import get_plugin


async def run_pipeline(nodes: list[dict[str, Any]], query: str, session: Any) -> dict[str, Any]:
    """Execute pipeline nodes in sequence: embed -> retrieve -> rerank -> generate."""
    contexts: list[dict[str, Any]] = []
    answer: str = ""
    traces: list[dict[str, Any]] = []

    # Phase 1: embed query (so retriever gets a query_vec for vector search)
    query_vec: list[float] | None = None
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
    for node in nodes:
        kind: str = node["plugin_kind"]
        name: str = node["plugin_name"]
        params: dict[str, Any] = dict(node.get("params", {}))

        cls = get_plugin(kind, name)
        if cls is None:
            raise ValueError(f"Plugin {kind}/{name} not found")

        if kind == "retriever":
            params["session"] = session
            retriever = cast(Retriever, cls(params))
            top_k = params.get("top_k", 10)
            contexts = await retriever.retrieve(
                query=query,
                top_k=top_k,
                organization_id=params.get("organization_id", ""),
                dataset_id=params.get("dataset_id"),
                query_vec=query_vec,
            )
            traces.append({"kind": kind, "name": name, "contexts_count": len(contexts)})

        elif kind == "reranker":
            params["session"] = session
            reranker = cast(Reranker, cls(params))
            top_k = params.get("top_k", 10)
            contexts = await reranker.rerank(query=query, candidates=contexts, top_k=top_k)
            traces.append({"kind": kind, "name": name, "reranked_count": len(contexts)})

        elif kind == "generator":
            params["session"] = session
            generator = cast(Generator, cls(params))
            result = await generator.generate(query=query, contexts=contexts)
            answer = result.get("answer", "")
            gen_trace = result.get("trace", {})
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
