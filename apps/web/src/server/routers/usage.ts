import { z } from "zod";
import { router, publicProcedure } from "../trpc";
import { API_URL } from "../api-url";

async function authedFetch(
  path: string,
  cookieHeader: string | null,
  options?: RequestInit
): Promise<Response> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(cookieHeader ? { cookie: cookieHeader } : {}),
      ...options?.headers,
    },
  });
  return res;
}

const ModelUsageSchema = z.object({
  model: z.string(),
  prompt_tokens: z.number(),
  completion_tokens: z.number(),
  cost_usd: z.number(),
  request_count: z.number(),
});

const DayUsageSchema = z.object({
  day: z.string(),
  models: z.array(ModelUsageSchema),
  total_cost_usd: z.number(),
});

const UsageSummarySchema = z.object({
  days: z.array(DayUsageSchema),
  total_cost_usd: z.number(),
  period_days: z.number(),
});

export type ModelUsage = z.infer<typeof ModelUsageSchema>;
export type DayUsage = z.infer<typeof DayUsageSchema>;
export type UsageSummary = z.infer<typeof UsageSummarySchema>;

export const usageRouter = router({
  summary: publicProcedure
    .input(
      z.object({
        orgId: z.string(),
        days: z.number().min(1).max(365).default(30),
      })
    )
    .query(async ({ input, ctx }) => {
      const res = await authedFetch(
        `/api/v1/orgs/${input.orgId}/usage/summary?days=${input.days}`,
        ctx.cookieHeader
      );
      if (res.status === 401) return null;
      if (!res.ok) throw new Error(`API ${res.status}`);
      const data = (await res.json()) as unknown;
      return UsageSummarySchema.parse(data);
    }),
});
