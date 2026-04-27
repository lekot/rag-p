import jsonschema

from ragp_api.plugins.registry import list_plugins

EXPECTED_KINDS = {"chunker", "embedder", "retriever", "reranker", "generator"}
EXPECTED_NAMES = {
    "recursive-character",
    "markdown-aware",
    "litellm-embedder",
    "pgvector-hybrid",
    "cohere",
    "litellm-generator",
}


def test_registry_has_all_six_plugins():
    plugins = list_plugins()
    names = {p["name"] for p in plugins}
    assert names == EXPECTED_NAMES, f"Missing plugins: {EXPECTED_NAMES - names}"


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
