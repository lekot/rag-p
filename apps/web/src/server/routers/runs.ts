import { z } from "zod";
import { router, protectedProcedure } from "../trpc";
import { apiClient } from "../api-client";

const ScoredChunkSchema = z.object({
  text: z.string(),
  score_bm25: z.number().optional(),
  score_dense: z.number().optional(),
  score_rrf: z.number().optional(),
  rank: z.number(),
});

const RerankedChunkSchema = z.object({
  text: z.string(),
  score_rerank: z.number().optional(),
  rerank_delta: z.number().optional(),
  rank: z.number(),
});

// Raw backend response may use either new scored format or old string[]
const RawRunDetailSchema = z.object({
  id: z.string(),
  status: z.string(),
  pipeline_id: z.string(),
  query: z.string(),
  chunks: z.union([
    z.array(ScoredChunkSchema),
    z.array(z.string()),
  ]).optional(),
  reranked_chunks: z.union([
    z.array(RerankedChunkSchema),
    z.array(z.string()),
  ]).optional(),
  answer: z.string().optional(),
  metrics: z
    .object({
      faithfulness: z.number().optional(),
      answer_relevance: z.number().optional(),
      context_precision: z.number().optional(),
      context_recall: z.number().optional(),
    })
    .optional(),
});

export type ScoredChunk = z.infer<typeof ScoredChunkSchema>;
export type RerankedChunk = z.infer<typeof RerankedChunkSchema>;

export type RunDetail = {
  id: string;
  status: string;
  pipeline_id: string;
  query: string;
  chunks?: ScoredChunk[];
  reranked_chunks?: RerankedChunk[];
  answer?: string;
  metrics?: {
    faithfulness?: number;
    answer_relevance?: number;
    context_precision?: number;
    context_recall?: number;
  };
};

/** Normalise backend response to always use scored format. */
function normaliseRun(raw: z.infer<typeof RawRunDetailSchema>): RunDetail {
  const chunks: ScoredChunk[] | undefined = raw.chunks
    ? (raw.chunks as Array<string | ScoredChunk>).map((c, i) =>
        typeof c === "string"
          ? { text: c, rank: i + 1 }
          : c
      )
    : undefined;

  const reranked_chunks: RerankedChunk[] | undefined = raw.reranked_chunks
    ? (raw.reranked_chunks as Array<string | RerankedChunk>).map((c, i) =>
        typeof c === "string"
          ? { text: c, rank: i + 1 }
          : c
      )
    : undefined;

  return {
    id: raw.id,
    status: raw.status,
    pipeline_id: raw.pipeline_id,
    query: raw.query,
    chunks,
    reranked_chunks,
    answer: raw.answer,
    metrics: raw.metrics,
  };
}

export const runsRouter = router({
  byId: protectedProcedure
    .input(z.object({ id: z.string() }))
    .query(async ({ input }) => {
      const raw = await apiClient.get<z.infer<typeof RawRunDetailSchema>>(
        `/api/v1/runs/${input.id}`
      );
      return normaliseRun(raw);
    }),
});
