from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel


class CostEstimate(BaseModel):
    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0
    note: str | None = None


class HealthStatus(BaseModel):
    ok: bool
    detail: str | None = None


class PluginBase(ABC):
    kind: ClassVar[str]
    name: ClassVar[str]
    version: ClassVar[str] = "0.1.0"
    params_schema: ClassVar[dict[str, Any]]

    def __init__(self, params: dict[str, Any]) -> None:
        defaults = self.params_schema.get("default", {}) if self.params_schema else {}
        self.params = {**defaults, **params}

    @abstractmethod
    async def cost_estimate(self, sample_input: Any) -> CostEstimate: ...

    @abstractmethod
    async def health_check(self) -> HealthStatus: ...


class Chunker(PluginBase):
    kind = "chunker"

    @abstractmethod
    async def chunk(self, text: str) -> list[dict[str, Any]]: ...


class Embedder(PluginBase):
    kind = "embedder"

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    @abstractmethod
    def dim(self) -> int: ...


class Retriever(PluginBase):
    kind = "retriever"

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        top_k: int,
        organization_id: str,
        dataset_id: str | None = None,
        query_vec: list[float] | None = None,
    ) -> list[dict[str, Any]]: ...


class Reranker(PluginBase):
    kind = "reranker"

    @abstractmethod
    async def rerank(
        self, query: str, candidates: list[dict[str, Any]], top_k: int
    ) -> list[dict[str, Any]]: ...


class Generator(PluginBase):
    kind = "generator"

    @abstractmethod
    async def generate(self, query: str, contexts: list[dict[str, Any]]) -> dict[str, Any]: ...
