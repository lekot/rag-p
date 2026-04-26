"""Langfuse tracing integration."""

from typing import Any

from ragp_api.settings import settings

_langfuse: Any = None


def get_langfuse() -> Any:
    """Get or create Langfuse client."""
    global _langfuse
    if _langfuse is not None:
        return _langfuse

    if not settings.langfuse_public_key:
        return None

    try:
        from langfuse import Langfuse

        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        return _langfuse
    except ImportError:
        # TODO: install langfuse package
        return None


def trace_run(run_id: str, pipeline_name: str, query: str, result: dict[str, Any]) -> None:
    """Create a Langfuse trace for a pipeline run."""
    client = get_langfuse()
    if client is None:
        return

    trace = client.trace(id=run_id, name=pipeline_name, input={"query": query})
    trace.update(output=result.get("answer", ""), metadata={"traces": result.get("traces", [])})
