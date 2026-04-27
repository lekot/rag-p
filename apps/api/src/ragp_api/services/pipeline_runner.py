"""Executes a pipeline on a single query."""

from typing import Any, cast

from ragp_api.plugins.base import Generator, Reranker, Retriever
from ragp_api.plugins.registry import get_plugin


async def run_pipeline(nodes: list[dict[str, Any]], query: str, session: Any) -> dict[str, Any]:
    """Execute pipeline nodes in sequence: retrieve -> rerank -> generate."""
    contexts: list[dict[str, Any]] = []
    answer: str = ""
    traces: list[dict[str, Any]] = []

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
                query=query, top_k=top_k, organization_id=params.get("organization_id", "")
            )
            traces.append({"kind": kind, "name": name, "contexts_count": len(contexts)})

        elif kind == "reranker":
            reranker = cast(Reranker, cls(params))
            top_k = params.get("top_k", 10)
            contexts = await reranker.rerank(query=query, candidates=contexts, top_k=top_k)
            traces.append({"kind": kind, "name": name, "reranked_count": len(contexts)})

        elif kind == "generator":
            generator = cast(Generator, cls(params))
            result = await generator.generate(query=query, contexts=contexts)
            answer = result.get("answer", "")
            traces.append({"kind": kind, "name": name, "trace": result.get("trace", {})})

        elif kind == "chunker":
            # chunker is used at ingest time, not query time
            traces.append({"kind": kind, "name": name, "skipped": "ingest-only"})

        elif kind == "embedder":
            # embedder is used at ingest and retrieval time inside retriever
            traces.append({"kind": kind, "name": name, "skipped": "handled-by-retriever"})

    return {"answer": answer, "contexts": contexts, "traces": traces}
