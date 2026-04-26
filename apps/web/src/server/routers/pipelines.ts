import { z } from "zod";
import { router, protectedProcedure } from "../trpc";
import { apiClient } from "../api-client";

const PipelineNodeSchema = z.object({
  plugin_kind: z.string(),
  plugin_name: z.string(),
  params: z.record(z.unknown()),
});

const CreatePipelineSchema = z.object({
  name: z.string().min(1),
  nodes: z.array(PipelineNodeSchema),
});

const PipelineSchema = z.object({
  id: z.string(),
  name: z.string(),
  organization_id: z.string(),
  nodes: z.array(PipelineNodeSchema),
});

export type Pipeline = z.infer<typeof PipelineSchema>;

export const pipelinesRouter = router({
  list: protectedProcedure.query(async ({ ctx }) => {
    return apiClient.get<Pipeline[]>(
      `/api/v1/pipelines?organization_id=${ctx.organization_id}`
    );
  }),

  byId: protectedProcedure
    .input(z.object({ id: z.string() }))
    .query(async ({ input }) => {
      return apiClient.get<Pipeline>(`/api/v1/pipelines/${input.id}`);
    }),

  create: protectedProcedure
    .input(CreatePipelineSchema)
    .mutation(async ({ input, ctx }) => {
      return apiClient.post<Pipeline>("/api/v1/pipelines", {
        ...input,
        organization_id: ctx.organization_id,
      });
    }),

  createRun: protectedProcedure
    .input(
      z.object({
        pipeline_id: z.string(),
        query: z.string().min(1),
        dataset_id: z.string().nullable().optional(),
      })
    )
    .mutation(async ({ input }) => {
      return apiClient.post<{ id: string; status: string }>(
        `/api/v1/pipelines/${input.pipeline_id}/runs`,
        { query: input.query, dataset_id: input.dataset_id ?? null }
      );
    }),
});
