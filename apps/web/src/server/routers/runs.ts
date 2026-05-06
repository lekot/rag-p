import { z } from "zod";
import { router, protectedProcedure } from "../trpc";
import { apiClient } from "../api-client";
import type { Context } from "../context";

function authHeaders(ctx: Pick<Context, "cookieHeader">): Record<string, string> {
  return ctx.cookieHeader ? { cookie: ctx.cookieHeader } : {};
}

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
  pipeline_id: z.string().optional(),
  pipeline_version_id: z.string().optional(),
  organization_id: z.string().optional(),
  dataset_id: z.string().nullable().optional(),
  query: z.string().nullable().optional(),
  metrics: z.record(z.unknown()).nullable().optional(),
  trace: z.record(z.unknown()).nullable().optional(),
  started_at: z.string().nullable().optional(),
  finished_at: z.string().nullable().optional(),
  created_at: z.string().optional(),
  chunks: z.union([
    z.array(ScoredChunkSchema),
    z.array(z.string()),
  ]).optional(),
  reranked_chunks: z.union([
    z.array(RerankedChunkSchema),
    z.array(z.string()),
  ]).optional(),
  answer: z.string().optional(),
});

export const RunListItemSchema = z.object({
  id: z.string(),
  organization_id: z.string(),
  pipeline_version_id: z.string(),
  dataset_id: z.string().nullable().optional(),
  query: z.string().nullable().optional(),
  status: z.string(),
  metrics: z.record(z.unknown()).nullable().optional(),
  trace: z.record(z.unknown()).nullable().optional(),
  started_at: z.string().nullable().optional(),
  finished_at: z.string().nullable().optional(),
  created_at: z.string(),
});

export type RunListItem = z.infer<typeof RunListItemSchema>;

export type ScoredChunk = z.infer<typeof ScoredChunkSchema>;
export type RerankedChunk = z.infer<typeof RerankedChunkSchema>;

export type RunDetail = {
  id: string;
  status: string;
  pipeline_id?: string;
  pipeline_version_id?: string;
  organization_id?: string;
  dataset_id?: string | null;
  query?: string | null;
  metrics?: Record<string, unknown> | null;
  trace?: Record<string, unknown> | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at?: string;
  chunks?: ScoredChunk[];
  reranked_chunks?: RerankedChunk[];
  answer?: string;
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
    pipeline_version_id: raw.pipeline_version_id,
    organization_id: raw.organization_id,
    dataset_id: raw.dataset_id,
    query: raw.query,
    metrics: raw.metrics,
    trace: raw.trace,
    started_at: raw.started_at,
    finished_at: raw.finished_at,
    created_at: raw.created_at,
    chunks,
    reranked_chunks,
    answer: raw.answer,
  };
}

export const runsRouter = router({
  list: protectedProcedure
    .input(z.object({ dataset_id: z.string().optional() }).optional())
    .query(async ({ input, ctx }) => {
      const params = new URLSearchParams();
      if (input?.dataset_id) params.set("dataset_id", input.dataset_id);
      const query = params.toString();
      const raw = await apiClient.get<z.infer<typeof RunListItemSchema>[]>(
        query ? `/api/v1/runs?${query}` : "/api/v1/runs",
        authHeaders(ctx)
      );
      return z.array(RunListItemSchema).parse(raw);
    }),

  byId: protectedProcedure
    .input(z.object({ id: z.string() }))
    .query(async ({ input, ctx }) => {
      const raw = await apiClient.get<z.infer<typeof RawRunDetailSchema>>(
        `/api/v1/runs/${input.id}`,
        authHeaders(ctx)
      );
      return normaliseRun(raw);
    }),
});
