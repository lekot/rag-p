"""MarkdownAwareChunker — wraps LangChain MarkdownHeaderTextSplitter."""

from typing import Any

from ragp_api.plugins.base import Chunker, CostEstimate, HealthStatus
from ragp_api.plugins.registry import register

_DEFAULT_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3")]


@register
class MarkdownAwareChunker(Chunker):
    name = "markdown-aware"
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
            from langchain_text_splitters import (
                MarkdownHeaderTextSplitter,
                RecursiveCharacterTextSplitter,
            )

            md_splitter = MarkdownHeaderTextSplitter(
                headers_to_split_on=_DEFAULT_HEADERS, strip_headers=False
            )
            header_splits = md_splitter.split_text(text)

            char_splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size, chunk_overlap=chunk_overlap
            )
            docs = char_splitter.split_documents(header_splits)
            return [{"text": d.page_content, "metadata": d.metadata} for d in docs]
        except ImportError:
            # TODO: install langchain-text-splitters to use full implementation
            return [{"text": text, "metadata": {"note": "fallback, no splitting"}}]

    async def cost_estimate(self, sample_input: Any) -> CostEstimate:
        return CostEstimate(note="local, no cost")

    async def health_check(self) -> HealthStatus:
        try:
            from langchain_text_splitters import MarkdownHeaderTextSplitter  # noqa: F401

            return HealthStatus(ok=True)
        except ImportError:
            return HealthStatus(
                ok=True, detail="langchain-text-splitters not installed, using fallback"
            )
