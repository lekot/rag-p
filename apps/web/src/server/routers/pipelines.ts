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
  dataset_id: z.string().nullable().optional(),
});

const PipelineSchema = z.object({
  id: z.string(),
  name: z.string(),
  organization_id: z.string(),
  current_version_id: z.string().nullable().optional(),
  dataset_id: z.string().nullable().optional(),
  nodes: z.array(PipelineNodeSchema),
});

export type Pipeline = z.infer<typeof PipelineSchema>;

const PipelineUpdateSchema = z.object({
  id: z.string(),
  name: z.string().min(1).optional(),
  nodes: z.array(PipelineNodeSchema).optional(),
});

export const pipelinesRouter = router({
  list: protectedProcedure
    .input(z.object({ datasetId: z.string().optional() }))
    .query(async ({ ctx, input }) => {
      const params = new URLSearchParams({
        organization_id: ctx.organization_id,
      });
      if (input.datasetId) {
        params.set("dataset_id", input.datasetId);
      }
      return apiClient.get<Pipeline[]>(`/api/v1/pipelines?${params.toString()}`);
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

  update: protectedProcedure
    .input(PipelineUpdateSchema)
    .mutation(async ({ input }) => {
      return apiClient.put<Pipeline>(`/api/v1/pipelines/${input.id}`, {
        name: input.name,
        nodes: input.nodes,
      });
    }),

  delete: protectedProcedure
    .input(z.object({ id: z.string() }))
    .mutation(async ({ input }) => {
      return apiClient.delete<void>(`/api/v1/pipelines/${input.id}`);
    }),
});
