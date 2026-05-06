"""Plugin registry — discovers plugins via importlib.metadata entrypoints."""

import logging
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from ragp_api.plugins.base import PluginBase

logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

_registry: dict[str, dict[str, type[PluginBase]]] = {}

_ENTRYPOINT_GROUPS = [
    "ragp.plugins.chunkers",
    "ragp.plugins.embedders",
    "ragp.plugins.retrievers",
    "ragp.plugins.rerankers",
    "ragp.plugins.generators",
]


def _is_current_project_entrypoint(ep: Any) -> bool:
    dist_path = getattr(getattr(ep, "dist", None), "_path", None)
    if dist_path is None:
        return False
    try:
        Path(dist_path).resolve().relative_to(_PROJECT_ROOT)
    except ValueError:
        return False
    return True


def _discover() -> None:
    for group in _ENTRYPOINT_GROUPS:
        for ep in entry_points(group=group):
            try:
                cls: type[PluginBase] = ep.load()
            except Exception:
                if _is_current_project_entrypoint(ep):
                    raise
                logger.warning(
                    "Skipping broken plugin entry point %s from %s",
                    ep.name,
                    ep.module,
                    exc_info=True,
                )
                continue
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
    """Import all built-in plugins so they self-register.

    Plugins that require an API key are only registered when the
    corresponding env var is set — keeps the UI clean and prevents
    users from selecting broken plugins.
    """
    import importlib.util  # noqa: PLC0415

    from ragp_api.plugins.chunkers import markdown, recursive
    from ragp_api.plugins.embedders import (  # noqa: F401
        litellm_embedder,
        ollama_embedder,
    )
    from ragp_api.plugins.generators import litellm_generator
    from ragp_api.plugins.rerankers import deepseek
    from ragp_api.plugins.retrievers import pgvector_hybrid

    for cls in (
        recursive.RecursiveCharacterChunker,
        markdown.MarkdownAwareChunker,
        litellm_embedder.LiteLLMEmbedder,
        ollama_embedder.OllamaEmbedder,
        pgvector_hybrid.PgvectorHybridRetriever,
        deepseek.DeepSeekReranker,
        litellm_generator.LiteLLMGenerator,
    ):
        register(cls)  # type: ignore[type-abstract]

    # BGE reranker requires sentence-transformers (optional dep).
    if importlib.util.find_spec("sentence_transformers") is not None:
        from ragp_api.plugins.rerankers import bge

        register(bge.BGEReranker)
