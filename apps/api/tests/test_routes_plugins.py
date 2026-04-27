import pytest
from httpx import AsyncClient

EXPECTED_KINDS = {"chunker", "embedder", "retriever", "reranker", "generator"}


@pytest.mark.asyncio
async def test_get_plugins_returns_list(client: AsyncClient):
    response = await client.get("/api/v1/plugins")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 6


@pytest.mark.asyncio
async def test_get_plugins_covers_all_kinds(client: AsyncClient):
    response = await client.get("/api/v1/plugins")
    assert response.status_code == 200
    data = response.json()
    kinds = {p["kind"] for p in data}
    assert kinds == EXPECTED_KINDS


@pytest.mark.asyncio
async def test_get_plugins_have_params_schema(client: AsyncClient):
    response = await client.get("/api/v1/plugins")
    assert response.status_code == 200
    for plugin in response.json():
        assert "params_schema" in plugin
        assert isinstance(plugin["params_schema"], dict)


@pytest.mark.asyncio
async def test_get_plugins_have_name_and_version(client: AsyncClient):
    response = await client.get("/api/v1/plugins")
    assert response.status_code == 200
    for plugin in response.json():
        assert plugin.get("name")
        assert plugin.get("version")
