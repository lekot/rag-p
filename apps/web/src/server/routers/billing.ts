import { z } from "zod";
import { router, publicProcedure } from "../trpc";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

const TransactionSchema = z.object({
  id: z.string(),
  type: z.string(),
  amount_usd: z.number(),
  balance_after_usd: z.number(),
  reference_type: z.string().nullable(),
  reference_id: z.string().nullable(),
  note: z.string().nullable(),
  created_at: z.string(),
});

const BillingSchema = z.object({
  balance_usd: z.number(),
  transactions: z.array(TransactionSchema),
});

export type BillingTransaction = z.infer<typeof TransactionSchema>;
export type BillingData = z.infer<typeof BillingSchema>;

export const billingRouter = router({
  get: publicProcedure
    .input(z.object({ orgId: z.string() }))
    .query(async ({ input, ctx }) => {
      const res = await authedFetch(
        `/api/v1/orgs/${input.orgId}/billing`,
        ctx.cookieHeader
      );
      if (res.status === 401) return null;
      if (!res.ok) throw new Error(`API ${res.status}`);
      const data = BillingSchema.parse(await res.json());
      return data;
    }),

  topup: publicProcedure
    .input(
      z.object({
        orgId: z.string(),
        amount_usd: z.number().positive(),
        note: z.string().optional(),
      })
    )
    .mutation(async ({ input, ctx }) => {
      const res = await authedFetch(
        `/api/v1/orgs/${input.orgId}/billing/topup`,
        ctx.cookieHeader,
        {
          method: "POST",
          body: JSON.stringify({
            amount_usd: input.amount_usd,
            note: input.note ?? null,
          }),
        }
      );
      if (res.status === 403) throw new Error("Insufficient permissions");
      if (!res.ok) throw new Error(`API ${res.status}`);
      return (await res.json()) as { balance_usd: number; transaction_id: string };
    }),
});
