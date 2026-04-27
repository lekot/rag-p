import { z } from "zod";
import { router, publicProcedure } from "../trpc";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const ApiKeySchema = z.object({
  id: z.string(),
  name: z.string(),
  key_prefix: z.string(),
  last_used_at: z.string().nullable().optional(),
  created_at: z.string(),
});

export type ApiKey = z.infer<typeof ApiKeySchema>;

const CreatedKeySchema = z.object({
  id: z.string(),
  key: z.string(),
  name: z.string(),
  key_prefix: z.string(),
});

export type CreatedKey = z.infer<typeof CreatedKeySchema>;

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

export const keysRouter = router({
  list: publicProcedure.query(async ({ ctx }) => {
    const res = await authedFetch("/api/v1/keys", ctx.cookieHeader);
    if (res.status === 401) return [] as ApiKey[];
    if (!res.ok) throw new Error(`API ${res.status}`);
    const data = (await res.json()) as unknown;
    return z.array(ApiKeySchema).parse(data);
  }),

  create: publicProcedure
    .input(z.object({ name: z.string().min(1) }))
    .mutation(async ({ input, ctx }) => {
      const res = await authedFetch("/api/v1/keys", ctx.cookieHeader, {
        method: "POST",
        body: JSON.stringify({ name: input.name }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => res.statusText);
        throw new Error(`API ${res.status}: ${text}`);
      }
      const data = (await res.json()) as unknown;
      return CreatedKeySchema.parse(data);
    }),

  delete: publicProcedure
    .input(z.object({ id: z.string() }))
    .mutation(async ({ input, ctx }) => {
      const res = await authedFetch(
        `/api/v1/keys/${input.id}`,
        ctx.cookieHeader,
        { method: "DELETE" }
      );
      if (res.status === 204 || res.ok) return { ok: true };
      const text = await res.text().catch(() => res.statusText);
      throw new Error(`API ${res.status}: ${text}`);
    }),
});
