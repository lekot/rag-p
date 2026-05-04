"""Plugin registry — discovers plugins via importlib.metadata entrypoints."""

from importlib.metadata import entry_points
from typing import Any

from ragp_api.plugins.base import PluginBase

_registry: dict[str, dict[str, type[PluginBase]]] = {}

_ENTRYPOINT_GROUPS = [
    "ragp.plugins.chunkers",
    "ragp.plugins.embedders",
    "ragp.plugins.retrievers",
    "ragp.plugins.rerankers",
    "ragp.plugins.generators",
]


def _discover() -> None:
    for group in _ENTRYPOINT_GROUPS:
        for ep in entry_points(group=group):
            cls: type[PluginBase] = ep.load()
            kind = cls.kind
            if kind not in _registry:
                _registry[kind] = {}
            _registry[kind][cls.name] = cls


def register(cls: type[PluginBase]) -> type[PluginBase]:
    """Decorator to register a plugin class manually."""
    kind = cls.kind
    if kind not in _registry:
        _registry[kind] = {}
    _registry[kind][cls.name] = cls
    return cls


def get_plugin(kind: str, name: str) -> type[PluginBase] | None:
    if not _registry:
        _discover()
    return _registry.get(kind, {}).get(name)


def list_plugins() -> list[dict[str, Any]]:
    if not _registry:
        _discover()
    result = []
    for kind, plugins in _registry.items():
        for name, cls in plugins.items():
            result.append(
                {
                    "kind": kind,
                    "name": name,
                    "version": cls.version,
                    "params_schema": cls.params_schema,
                    "default_params": cls.params_schema.get("default", {}),
                }
            )
    return result


def bootstrap() -> None:
    """Import all built-in plugins so they self-register."""
    # BGE reranker requires sentence-transformers (optional dep).
    # Only register it if the package is available — avoids showing a
    # broken plugin in the UI and prevents runtime errors.
    import importlib.util  # noqa: PLC0415

    from ragp_api.plugins.chunkers import markdown, recursive  # noqa: F401
    from ragp_api.plugins.embedders import (  # noqa: F401
        cohere_embedder,
        litellm_embedder,
        ollama_embedder,
    )
    from ragp_api.plugins.generators import litellm_generator  # noqa: F401
    from ragp_api.plugins.rerankers import (
        cohere,  # noqa: F401
        deepseek,  # noqa: F401
    )

    if importlib.util.find_spec("sentence_transformers") is not None:
        from ragp_api.plugins.rerankers import bge  # noqa: F401
    from ragp_api.plugins.retrievers import pgvector_hybrid  # noqa: F401
