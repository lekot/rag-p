import { z } from "zod";
import { router, protectedProcedure } from "../trpc";
import { apiClient } from "../api-client";

const DatasetSchema = z.object({
  id: z.string(),
  name: z.string(),
  source: z.string().optional(),
  organization_id: z.string(),
  size: z.number().optional(),
});

export type Dataset = z.infer<typeof DatasetSchema>;

const DocumentSummarySchema = z.object({
  id: z.string(),
  source_uri: z.string(),
  status: z.string(),
  parsed_at: z.string().nullable().optional(),
  chunk_count: z.number(),
});

export type DocumentSummary = z.infer<typeof DocumentSummarySchema>;

const ChunkSchema = z.object({
  index: z.number(),
  text: z.string(),
  len: z.number(),
  metadata: z.record(z.unknown()),
  has_embedding: z.boolean().optional(),
});

export type Chunk = z.infer<typeof ChunkSchema>;

const SearchChunkSchema = z.object({
  id: z.string(),
  text: z.string(),
  score: z.number(),
  metadata: z.record(z.unknown()),
  document_id: z.string(),
  document_name: z.string(),
});

export type SearchChunk = z.infer<typeof SearchChunkSchema>;

const SearchResultSchema = z.object({
  chunks: z.array(SearchChunkSchema),
});

const AskUsageSchema = z.object({
  prompt_tokens: z.number(),
  completion_tokens: z.number(),
});

const AskResultSchema = z.object({
  answer: z.string(),
  chunks: z.array(SearchChunkSchema),
  usage: AskUsageSchema,
});

export type AskResult = z.infer<typeof AskResultSchema>;

const DocumentDetailSchema = z.object({
  id: z.string(),
  source_uri: z.string(),
  status: z.string(),
  parsed_at: z.string().nullable().optional(),
  chunk_count: z.number(),
  chunks: z.array(ChunkSchema),
});

export type DocumentDetail = z.infer<typeof DocumentDetailSchema>;

export const datasetsRouter = router({
  list: protectedProcedure.query(async ({ ctx }) => {
    return apiClient.get<Dataset[]>(
      `/api/v1/datasets?organization_id=${ctx.organization_id}`
    );
  }),

  byId: protectedProcedure
    .input(z.object({ id: z.string() }))
    .query(async ({ input, ctx }) => {
      return apiClient.get<Dataset>(`/api/v1/datasets/${input.id}`, {
        "x-organization-id": ctx.organization_id,
      });
    }),

  create: protectedProcedure
    .input(
      z.object({
        name: z.string().min(1),
        source: z.string().optional(),
      })
    )
    .mutation(async ({ input, ctx }) => {
      return apiClient.post<Dataset>("/api/v1/datasets", {
        ...input,
        organization_id: ctx.organization_id,
      });
    }),

  generate: protectedProcedure
    .input(z.object({ id: z.string() }))
    .mutation(async ({ input }) => {
      return apiClient.post<{ status: string }>(
        `/api/v1/datasets/${input.id}/generate`,
        {}
      );
    }),

  search: protectedProcedure
    .input(
      z.object({
        datasetId: z.string(),
        query: z.string().min(1),
        top_k: z.number().int().min(1).max(50).default(10),
      })
    )
    .mutation(async ({ input, ctx }) => {
      return apiClient.post<z.infer<typeof SearchResultSchema>>(
        `/api/v1/datasets/${input.datasetId}/search`,
        { query: input.query, top_k: input.top_k },
        { "x-organization-id": ctx.organization_id }
      );
    }),

  ask: protectedProcedure
    .input(
      z.object({
        datasetId: z.string(),
        query: z.string().min(1),
        top_k: z.number().int().min(1).max(50).default(5),
        model: z.string().default("deepseek/deepseek-v4-flash"),
        pipeline_id: z.string().nullable().optional(),
      })
    )
    .mutation(async ({ input, ctx }) => {
      return apiClient.post<z.infer<typeof AskResultSchema>>(
        `/api/v1/datasets/${input.datasetId}/ask`,
        {
          query: input.query,
          top_k: input.top_k,
          model: input.model,
          pipeline_id: input.pipeline_id ?? null,
        },
        { "x-organization-id": ctx.organization_id }
      );
    }),

  documents: router({
    list: protectedProcedure
      .input(z.object({ datasetId: z.string() }))
      .query(async ({ input }) => {
        return apiClient.get<DocumentSummary[]>(
          `/api/v1/datasets/${input.datasetId}/documents`
        );
      }),

    byId: protectedProcedure
      .input(z.object({ datasetId: z.string(), docId: z.string() }))
      .query(async ({ input }) => {
        return apiClient.get<DocumentDetail>(
          `/api/v1/datasets/${input.datasetId}/documents/${input.docId}`
        );
      }),
  }),
});
