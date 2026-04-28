import { initTRPC, TRPCError } from "@trpc/server";
import superjson from "superjson";
import type { Context } from "./context";

const t = initTRPC.context<Context>().create({
  transformer: superjson,
});

export const router = t.router;
export const publicProcedure = t.procedure;

/** Procedure that requires an authenticated organization context. */
export const protectedProcedure = t.procedure.use(({ ctx, next }) => {
  if (!ctx.organization_id || !ctx.cookieHeader) {
    throw new TRPCError({ code: "UNAUTHORIZED" });
  }
  return next({ ctx: { ...ctx, organization_id: ctx.organization_id } });
});
