import { z } from "zod";
import { router, protectedProcedure } from "../trpc";
import { apiClient } from "../api-client";

const RunDetailSchema = z.object({
  id: z.string(),
  status: z.string(),
  pipeline_id: z.string(),
  query: z.string(),
  chunks: z.array(z.string()).optional(),
  reranked_chunks: z.array(z.string()).optional(),
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

export type RunDetail = z.infer<typeof RunDetailSchema>;

export const runsRouter = router({
  byId: protectedProcedure
    .input(z.object({ id: z.string() }))
    .query(async ({ input }) => {
      return apiClient.get<RunDetail>(`/api/v1/runs/${input.id}`);
    }),
});
