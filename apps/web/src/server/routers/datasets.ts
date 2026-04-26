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

export const datasetsRouter = router({
  list: protectedProcedure.query(async ({ ctx }) => {
    return apiClient.get<Dataset[]>(
      `/api/v1/datasets?organization_id=${ctx.organization_id}`
    );
  }),

  create: protectedProcedure
    .input(
      z.object({
        name: z.string().min(1),
        source: z.string(),
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
});
