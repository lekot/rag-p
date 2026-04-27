"""PgvectorHybridRetriever — tsvector + pgvector + RRF fusion."""

from typing import Any

from ragp_api.plugins.base import CostEstimate, HealthStatus, Retriever
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

    async def retrieve(
        self,
        query: str,
        top_k: int,
        organization_id: str,
        dataset_id: str | None = None,
        query_vec: list[float] | None = None,
    ) -> list[dict]:
        """Requires a live DB session injected via params['session'] at call time.

        Args:
            query: raw query text (used for BM25 branch).
            top_k: number of results to return.
            organization_id: tenant scope.
            dataset_id: optional — if set, restrict to chunks from that dataset.
            query_vec: pre-computed dense embedding; if None the retriever
                       calls litellm internally (legacy path).
        """
        session = self.params.get("session")
        if session is None:
            raise RuntimeError("PgvectorHybridRetriever requires 'session' in params at call time")

        from sqlalchemy import text

        weight_dense: float = self.params.get("weight_dense", 0.7)
        weight_bm25: float = self.params.get("weight_bm25", 0.3)

        if query_vec is None:
            embedding_model: str = self.params.get(
                "embedding_model", "openai/text-embedding-3-small"
            )
            import litellm

            embed_resp = await litellm.aembedding(model=embedding_model, input=[query])
            query_vec = embed_resp.data[0]["embedding"]

        vec_str = "[" + ",".join(str(v) for v in query_vec) + "]"

        # Optional dataset filter clause
        dataset_filter = "AND d.dataset_id = :dataset_id" if dataset_id is not None else ""

        sql = text(
            f"""
            WITH dense AS (
                SELECT
                    c.id, c.text, c.metadata_json, c.document_id,
                    ROW_NUMBER() OVER (
                        ORDER BY c.embedding <-> CAST(:query_vec AS vector)
                    ) AS rank
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE d.organization_id = :org_id
                  AND c.embedding IS NOT NULL
                  {dataset_filter}
                ORDER BY c.embedding <-> CAST(:query_vec AS vector)
                LIMIT :top_k
            ),
            bm25 AS (
                SELECT c.id, c.text, c.metadata_json, c.document_id,
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
                  {dataset_filter}
                ORDER BY ts_rank_cd(
                    to_tsvector('english', c.text),
                    plainto_tsquery('english', :query)
                ) DESC
                LIMIT :top_k
            ),
            rrf AS (
                SELECT
                    COALESCE(dense.id, bm25.id) AS id,
                    COALESCE(dense.text, bm25.text) AS text,
                    COALESCE(dense.metadata_json, bm25.metadata_json) AS metadata_json,
                    COALESCE(dense.document_id, bm25.document_id) AS document_id,
                    :weight_dense * (1.0 / (:rrf_k + COALESCE(dense.rank, 1e9))) +
                    :weight_bm25 * (1.0 / (:rrf_k + COALESCE(bm25.rank, 1e9))) AS score
                FROM dense
                FULL OUTER JOIN bm25 ON bm25.id = dense.id
            )
            SELECT rrf.id, rrf.text, rrf.metadata_json, rrf.document_id,
                   doc.source_uri AS document_name, rrf.score
            FROM rrf
            JOIN documents doc ON doc.id = rrf.document_id
            ORDER BY score DESC
            LIMIT :top_k
            """
        )

        params: dict = {
            "query_vec": vec_str,
            "query": query,
            "org_id": organization_id,
            "top_k": top_k,
            "weight_dense": weight_dense,
            "weight_bm25": weight_bm25,
            "rrf_k": _RRF_K,
        }
        if dataset_id is not None:
            params["dataset_id"] = dataset_id

        result = await session.execute(sql, params)
        rows = result.fetchall()
        return [
            {
                "id": row.id,
                "text": row.text,
                "metadata": row.metadata_json or {},
                "score": float(row.score),
                "document_id": row.document_id,
                "document_name": row.document_name,
            }
            for row in rows
        ]

    async def cost_estimate(self, sample_input: Any) -> CostEstimate:
        return CostEstimate(note="DB query cost depends on index size")

    async def health_check(self) -> HealthStatus:
        return HealthStatus(ok=True, detail="requires live DB to verify pgvector extension")
