import { z } from "zod";
import { router, protectedProcedure } from "../trpc";
import { apiClient } from "../api-client";

const PluginOptionSchema = z.object({
  name: z.string(),
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
});

export type Experiment = z.infer<typeof ExperimentSchema>;

const ScoresSchema = z.object({
  faithfulness: z.number().optional(),
  answer_relevance: z.number().optional(),
  context_precision: z.number().optional(),
  context_recall: z.number().optional(),
});

const LeaderboardCombinationSchema = z.object({
  config: z.record(z.unknown()),
  scores: ScoresSchema,
  composite_score: z.number(),
});

export type LeaderboardCombination = z.infer<typeof LeaderboardCombinationSchema>;

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
      return apiClient.post<{ id: string }>("/api/v1/experiments", {
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
});
