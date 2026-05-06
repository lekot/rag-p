from importlib.util import find_spec

import jsonschema
import pytest

from ragp_api.plugins import registry
from ragp_api.plugins.base import PluginBase
from ragp_api.plugins.registry import list_plugins

EXPECTED_KINDS = {"chunker", "embedder", "retriever", "reranker", "generator"}
EXPECTED_NAMES = {
    "recursive-character",
    "markdown-aware",
    "litellm-embedder",
    "ollama-embedder",
    "pgvector-hybrid",
    "deepseek-rerank",
    "litellm-generator",
}
if find_spec("sentence_transformers") is not None:
    EXPECTED_NAMES.add("bge-reranker")


def test_registry_has_all_expected_plugins():
    plugins = list_plugins()
    names = {p["name"] for p in plugins}
    assert (
        names == EXPECTED_NAMES
    ), f"Missing: {EXPECTED_NAMES - names}; extra: {names - EXPECTED_NAMES}"


def test_registry_covers_all_kinds():
    plugins = list_plugins()
    kinds = {p["kind"] for p in plugins}
    assert kinds == EXPECTED_KINDS


def test_all_params_schemas_are_valid():
    plugins = list_plugins()
    for plugin in plugins:
        schema = plugin["params_schema"]
        # raises jsonschema.SchemaError if invalid
        jsonschema.Draft202012Validator.check_schema(schema)


def test_plugin_has_version():
    plugins = list_plugins()
    for plugin in plugins:
        assert plugin["version"], f"Plugin {plugin['name']} has no version"


def test_plugin_has_default_params():
    plugins = list_plugins()
    for plugin in plugins:
        assert "default_params" in plugin, f"Plugin {plugin['name']} missing default_params key"


class _FakeExternalPlugin(PluginBase):
    kind = "embedder"
    name = "fake-external"
    version = "0.1.0"
    params_schema = {"type": "object", "default": {}}

    async def cost_estimate(self, sample_input):
        raise NotImplementedError

    async def health_check(self):
        raise NotImplementedError


class _FakeDist:
    def __init__(self, path):
        self._path = path


class _FakeEntryPoint:
    def __init__(self, name, module, loaded=None, error=None, dist_path=None):
        self.name = name
        self.module = module
        self._loaded = loaded
        self._error = error
        self.dist = _FakeDist(dist_path) if dist_path is not None else None

    def load(self):
        if self._error is not None:
            raise self._error
        return self._loaded


def test_broken_external_entrypoint_is_logged_and_skipped(monkeypatch, caplog):
    def fake_entry_points(group):
        assert group in registry._ENTRYPOINT_GROUPS
        if group != "ragp.plugins.embedders":
            return []
        return [
            _FakeEntryPoint(
                name="broken-cohere",
                module="cohere_embedder.plugin",
                error=ModuleNotFoundError("No module named 'cohere_embedder.plugin'"),
            ),
            _FakeEntryPoint(
                name="fake-external",
                module="fake_external.plugin",
                loaded=_FakeExternalPlugin,
            ),
        ]

    monkeypatch.setattr(registry, "entry_points", fake_entry_points)
    registry._registry.clear()

    with caplog.at_level("WARNING", logger="ragp_api.plugins.registry"):
        plugins = list_plugins()

    assert [plugin["name"] for plugin in plugins] == ["fake-external"]
    assert "Skipping broken plugin entry point broken-cohere" in caplog.text
    assert "cohere_embedder.plugin" in caplog.text


def test_broken_builtin_entrypoint_is_not_skipped(monkeypatch):
    def fake_entry_points(group):
        if group != "ragp.plugins.embedders":
            return []
        return [
            _FakeEntryPoint(
                name="broken-builtin",
                module="ragp_api.plugins.embedders.broken",
                error=RuntimeError("built-in import failed"),
                dist_path=registry._PROJECT_ROOT / "ragp_api-0.1.0.dist-info",
            )
        ]

    monkeypatch.setattr(registry, "entry_points", fake_entry_points)
    registry._registry.clear()

    with pytest.raises(RuntimeError, match="built-in import failed"):
        list_plugins()
