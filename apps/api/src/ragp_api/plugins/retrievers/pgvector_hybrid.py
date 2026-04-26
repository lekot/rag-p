"""PgvectorHybridRetriever — tsvector + pgvector + RRF fusion."""

from typing import Any

from ragp_api.plugins.base import Retriever, CostEstimate, HealthStatus
from ragp_api.plugins.registry import register

_RRF_K = 60


@register
class PgvectorHybridRetriever(Retriever):
    name = "pgvector-hybrid"
    version = "0.1.0"
    params_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "weight_dense": {"type": "number", "default": 0.7, "minimum": 0, "maximum": 1},
            "weight_bm25": {"type": "number", "default": 0.3, "minimum": 0, "maximum": 1},
            "top_k": {"type": "integer", "default": 10, "minimum": 1},
            "embedding_model": {"type": "string", "default": "openai/text-embedding-3-small"},
        },
        "required": [],
        "default": {
            "weight_dense": 0.7,
            "weight_bm25": 0.3,
            "top_k": 10,
            "embedding_model": "openai/text-embedding-3-small",
        },
    }

    async def retrieve(self, query: str, top_k: int, organization_id: str) -> list[dict]:
        """Requires a live DB session injected via params['session'] at call time."""
        session = self.params.get("session")
        if session is None:
            # TODO: inject session via dependency injection at call site
            raise RuntimeError("PgvectorHybridRetriever requires 'session' in params at call time")

        from sqlalchemy import text

        weight_dense: float = self.params.get("weight_dense", 0.7)
        weight_bm25: float = self.params.get("weight_bm25", 0.3)
        embedding_model: str = self.params.get("embedding_model", "openai/text-embedding-3-small")

        import litellm

        embed_resp = await litellm.aembedding(model=embedding_model, input=[query])
        query_vec = embed_resp.data[0]["embedding"]
        vec_str = "[" + ",".join(str(v) for v in query_vec) + "]"

        sql = text(
            """
            WITH dense AS (
                SELECT c.id, c.text, c.metadata_json,
                       ROW_NUMBER() OVER (ORDER BY c.embedding <-> CAST(:query_vec AS vector)) AS rank
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE d.organization_id = :org_id
                  AND c.embedding IS NOT NULL
                ORDER BY c.embedding <-> CAST(:query_vec AS vector)
                LIMIT :top_k
            ),
            bm25 AS (
                SELECT c.id, c.text, c.metadata_json,
                       ROW_NUMBER() OVER (
                           ORDER BY ts_rank_cd(
                               to_tsvector('english', c.text),
                               plainto_tsquery('english', :query)
                           ) DESC
                       ) AS rank
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE d.organization_id = :org_id
                  AND c.text != ''
                ORDER BY ts_rank_cd(
                    to_tsvector('english', c.text),
                    plainto_tsquery('english', :query)
                ) DESC
                LIMIT :top_k
            ),
            rrf AS (
                SELECT
                    COALESCE(d.id, b.id) AS id,
                    COALESCE(d.text, b.text) AS text,
                    COALESCE(d.metadata_json, b.metadata_json) AS metadata_json,
                    :weight_dense * (1.0 / (:rrf_k + COALESCE(d.rank, 1e9))) +
                    :weight_bm25 * (1.0 / (:rrf_k + COALESCE(b.rank, 1e9))) AS score
                FROM dense d
                FULL OUTER JOIN bm25 b ON b.id = d.id
            )
            SELECT id, text, metadata_json, score
            FROM rrf
            ORDER BY score DESC
            LIMIT :top_k
            """
        )

        result = await session.execute(
            sql,
            {
                "query_vec": vec_str,
                "query": query,
                "org_id": organization_id,
                "top_k": top_k,
                "weight_dense": weight_dense,
                "weight_bm25": weight_bm25,
                "rrf_k": _RRF_K,
            },
        )
        rows = result.fetchall()
        return [
            {
                "id": row.id,
                "text": row.text,
                "metadata": row.metadata_json or {},
                "score": float(row.score),
            }
            for row in rows
        ]

    async def cost_estimate(self, sample_input: Any) -> CostEstimate:
        return CostEstimate(note="DB query cost depends on index size")

    async def health_check(self) -> HealthStatus:
        return HealthStatus(ok=True, detail="requires live DB to verify pgvector extension")
