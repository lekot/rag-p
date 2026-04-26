import { z } from "zod";
import { router, protectedProcedure } from "../trpc";
import { apiClient } from "../api-client";

const PluginSchema = z.object({
  kind: z.enum(["chunker", "embedder", "retriever", "reranker", "generator"]),
  name: z.string(),
  version: z.string(),
  params_schema: z.record(z.unknown()),
  default_params: z.record(z.unknown()),
});

export type Plugin = z.infer<typeof PluginSchema>;

export const pluginsRouter = router({
  list: protectedProcedure.query(async () => {
    return apiClient.get<Plugin[]>("/api/v1/plugins");
  }),
});
