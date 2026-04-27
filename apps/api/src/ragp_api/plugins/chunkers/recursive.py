"""RecursiveCharacterChunker — wraps LangChain RecursiveCharacterTextSplitter."""

from typing import Any

from ragp_api.plugins.base import Chunker, CostEstimate, HealthStatus
from ragp_api.plugins.registry import register


@register
class RecursiveCharacterChunker(Chunker):
    name = "recursive-character"
    version = "0.1.0"
    params_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "chunk_size": {"type": "integer", "default": 512, "minimum": 64},
            "chunk_overlap": {"type": "integer", "default": 64, "minimum": 0},
        },
        "required": [],
        "default": {"chunk_size": 512, "chunk_overlap": 64},
    }

    async def chunk(self, text: str) -> list[dict]:
        chunk_size: int = self.params.get("chunk_size", 512)
        chunk_overlap: int = self.params.get("chunk_overlap", 64)

        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter

            splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size, chunk_overlap=chunk_overlap
            )
            docs = splitter.create_documents([text])
            return [{"text": d.page_content, "metadata": d.metadata} for d in docs]
        except ImportError:
            # TODO: install langchain-text-splitters to use full implementation
            step = max(1, chunk_size - chunk_overlap)
            chunks = []
            for i in range(0, len(text), step):
                chunk_text = text[i : i + chunk_size]
                if chunk_text:
                    chunks.append({"text": chunk_text, "metadata": {"start": i}})
            return chunks

    async def cost_estimate(self, sample_input: Any) -> CostEstimate:
        return CostEstimate(note="local, no cost")

    async def health_check(self) -> HealthStatus:
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: F401

            return HealthStatus(ok=True)
        except ImportError:
            return HealthStatus(
                ok=True, detail="langchain-text-splitters not installed, using fallback"
            )
