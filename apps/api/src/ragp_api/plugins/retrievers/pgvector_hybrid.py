"""PgvectorHybridRetriever — tsvector + pgvector + RRF fusion."""

import logging
from typing import Any, ClassVar

from ragp_api.plugins.base import CostEstimate, HealthStatus, Retriever
from ragp_api.plugins.registry import register

_RRF_K = 60

logger = logging.getLogger(__name__)


@register
class PgvectorHybridRetriever(Retriever):
    name = "pgvector-hybrid"
    version = "0.1.0"
    params_schema: ClassVar[dict[str, Any]] = {
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
    ) -> list[dict[str, Any]]:
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

        # Optional dataset filter clause
        dataset_filter = "AND d.dataset_id = :dataset_id" if dataset_id is not None else ""

        if query_vec is None:
            sql = text(
                f"""
                SELECT c.id, c.text, c.metadata_json, c.document_id,
                       doc.source_uri AS document_name,
                       ts_rank_cd(
                           to_tsvector('english', c.text),
                           plainto_tsquery('english', :query)
                       ) AS score
                FROM chunks c
                JOIN documents doc ON doc.id = c.document_id
                JOIN documents d ON d.id = c.document_id
                WHERE d.organization_id = :org_id
                  AND c.text != ''
                  {dataset_filter}
                ORDER BY score DESC
                LIMIT :top_k
                """
            )
            bm25_params: dict[str, Any] = {
                "query": query,
                "org_id": organization_id,
                "top_k": top_k,
            }
            if dataset_id is not None:
                bm25_params["dataset_id"] = dataset_id

            result = await session.execute(sql, bm25_params)
            rows = result.fetchall()

            if not rows:
                # Fallback: try simple token matching (works better for non-English)
                logger.info(
                    "BM25 returned 0 rows for org=%s dataset=%s query=%r — trying simple fallback",
                    organization_id, dataset_id, query[:80],
                )
                # Extract alphanumeric tokens from query for basic matching
                import re

                tokens = re.findall(r"[\wа-яёА-ЯЁ]+(?::\w+)*", query.lower())
                if tokens:
                    simple_query = " | ".join(tokens[:20])  # OR-based fallback
                    fallback_sql = text(
                        f"""
                        SELECT c.id, c.text, c.metadata_json, c.document_id,
                               doc.source_uri AS document_name,
                               ts_rank_cd(
                                   to_tsvector('simple', c.text),
                                   to_tsquery('simple', :simple_query)
                               ) AS score
                        FROM chunks c
                        JOIN documents doc ON doc.id = c.document_id
                        JOIN documents d ON d.id = c.document_id
                        WHERE d.organization_id = :org_id
                          AND c.text != ''
                          {dataset_filter}
                          AND to_tsvector('simple', c.text) @@ to_tsquery('simple', :simple_query)
                        ORDER BY score DESC
                        LIMIT :top_k
                        """
                    )
                    fb_params: dict[str, Any] = {
                        "simple_query": simple_query,
                        "org_id": organization_id,
                        "top_k": top_k,
                    }
                    if dataset_id is not None:
                        fb_params["dataset_id"] = dataset_id
                    try:
                        fb_result = await session.execute(fallback_sql, fb_params)
                        rows = fb_result.fetchall()
                        if rows:
                            logger.info(
                                "Simple fallback found %d rows for org=%s",
                                len(rows), organization_id,
                            )
                    except Exception as fb_exc:
                        logger.warning("Simple fallback query failed: %s", fb_exc)

                if not rows:
                    logger.warning(
                        "BM25 + simple fallback returned 0 rows for org=%s query=%r",
                        organization_id, query[:80],
                    )

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

        vec_str = "[" + ",".join(str(v) for v in query_vec) + "]"

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

        params: dict[str, Any] = {
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

        if not rows:
            # Diagnostic: check if chunks exist for this org/dataset
            from sqlalchemy import text as sql_text

            try:
                diag_sql = (
                    """
                    SELECT count(*) FILTER (WHERE c.embedding IS NOT NULL) AS with_embedding,
                           count(*) FILTER (WHERE c.embedding IS NULL) AS without_embedding
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.organization_id = :org_id
                      AND c.text != ''
                    """
                    + dataset_filter
                )
                diag = await session.execute(
                    sql_text(diag_sql),
                    params,
                )
                (emb_count, no_emb_count) = diag.one()
                logger.warning(
                    "Hybrid retrieve returned 0 rows for org=%s dataset=%s query=%r "
                    "dense_vec=%s. Chunks in scope: %d with emb, %d without emb",
                    organization_id, dataset_id, query[:80],
                    "provided" if query_vec is not None else "none",
                    emb_count, no_emb_count,
                )
            except Exception as diag_exc:
                logger.warning("Diagnostic query failed: %s", diag_exc)

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
