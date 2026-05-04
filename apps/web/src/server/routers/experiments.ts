import { z } from "zod";
import { router, protectedProcedure } from "../trpc";
import { apiClient } from "../api-client";

const PluginOptionSchema = z.object({
  plugin_kind: z.string(),
  plugin_name: z.string(),
  params: z.record(z.unknown()),
});

const CreateExperimentSchema = z.object({
  name: z.string().min(1),
  dataset_id: z.string(),
  plugin_grid: z.object({
    chunkers: z.array(PluginOptionSchema),
    embedders: z.array(PluginOptionSchema).optional(),
    retrievers: z.array(PluginOptionSchema).optional(),
    rerankers: z.array(PluginOptionSchema).optional(),
    generators: z.array(PluginOptionSchema).optional(),
  }),
});

const ExperimentSchema = z.object({
  id: z.string(),
  name: z.string(),
  dataset_id: z.string(),
  organization_id: z.string(),
  status: z.string().optional(),
  plugin_grid: z.record(z.unknown()).nullable().optional(),
  leaderboard: z.array(z.unknown()).nullable().optional(),
  created_at: z.string().nullable().optional(),
});

export type Experiment = z.infer<typeof ExperimentSchema>;

const ScoresSchema = z.object({
  faithfulness: z.number().nullable().optional(),
  answer_relevance: z.number().nullable().optional(),
  context_precision: z.number().nullable().optional(),
  context_recall: z.number().nullable().optional(),
  retrieval_hit: z.number().nullable().optional(),
  hit_rate: z.number().nullable().optional(),
  answer_similarity: z.number().nullable().optional(),
});

const LeaderboardCombinationSchema = z.object({
  config: z.record(z.unknown()),
  scores: ScoresSchema,
  composite_score: z.number(),
  status: z.string().optional(),
  error_code: z.string().nullable().optional(),
  error: z.string().nullable().optional(),
  warning: z.string().nullable().optional(),
  traces: z.array(z.record(z.unknown())).optional(),
});

export type LeaderboardCombination = z.infer<typeof LeaderboardCombinationSchema>;

const PromotePipelineSchema = z.object({
  id: z.string(),
  name: z.string(),
  organization_id: z.string(),
  current_version_id: z.string().nullable().optional(),
  dataset_id: z.string().nullable().optional(),
  nodes: z.array(z.object({
    plugin_kind: z.string(),
    plugin_name: z.string(),
    params: z.record(z.unknown()),
  })),
});

export type PromotedPipeline = z.infer<typeof PromotePipelineSchema>;

export const experimentsRouter = router({
  list: protectedProcedure.query(async ({ ctx }) => {
    return apiClient.get<Experiment[]>(
      `/api/v1/experiments?organization_id=${ctx.organization_id}`
    );
  }),

  byId: protectedProcedure
    .input(z.object({ id: z.string() }))
    .query(async ({ input }) => {
      return apiClient.get<Experiment>(`/api/v1/experiments/${input.id}`);
    }),

  create: protectedProcedure
    .input(CreateExperimentSchema)
    .mutation(async ({ input, ctx }) => {
      return apiClient.post<Experiment>("/api/v1/experiments", {
        ...input,
        organization_id: ctx.organization_id,
      });
    }),

  leaderboard: protectedProcedure
    .input(z.object({ id: z.string() }))
    .query(async ({ input }) => {
      return apiClient.get<{ combinations: LeaderboardCombination[] }>(
        `/api/v1/experiments/${input.id}/leaderboard`
      );
    }),

  promote: protectedProcedure
    .input(z.object({ id: z.string(), name: z.string().min(1) }))
    .mutation(async ({ input }) => {
      return apiClient.post<PromotedPipeline>(
        `/api/v1/experiments/${input.id}/promote_to_pipeline`,
        { name: input.name }
      );
    }),
});
