import { z } from "zod";
import { TRPCError } from "@trpc/server";
import { router, publicProcedure } from "../trpc";
import { apiFetchWithCookies } from "../api-client";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const UserSchema = z.object({
  id: z.string(),
  email: z.string(),
});

const OrganizationSchema = z.object({
  id: z.string(),
  name: z.string(),
  slug: z.string(),
  role: z.string(),
});

const MeResponseSchema = z.object({
  user: UserSchema,
  organization: OrganizationSchema,
});

export type MeResponse = z.infer<typeof MeResponseSchema>;

const AuthResponseSchema = z.object({
  user: UserSchema,
  organization: OrganizationSchema,
});

export const authRouter = router({
  me: publicProcedure.query(async ({ ctx }) => {
    if (!ctx.cookieHeader) return null;
    try {
      const res = await fetch(`${API_URL}/api/v1/auth/me`, {
        headers: {
          "Content-Type": "application/json",
          cookie: ctx.cookieHeader,
        },
      });
      if (res.status === 401) return null;
      if (!res.ok) return null;
      const data = (await res.json()) as unknown;
      return MeResponseSchema.parse(data);
    } catch {
      return null;
    }
  }),

  signup: publicProcedure
    .input(
      z.object({
        email: z.string().email(),
        password: z.string().min(1),
        organization_name: z.string().optional(),
      })
    )
    .mutation(async ({ input, ctx: _ctx }) => {
      const { data, rawResponse } = await apiFetchWithCookies<unknown>(
        "/api/v1/auth/signup",
        {
          method: "POST",
          body: JSON.stringify(input),
          headers: { "Content-Type": "application/json" },
        }
      );
      const parsed = AuthResponseSchema.parse(data);
      const setCookie = rawResponse.headers.get("set-cookie");
      return { ...parsed, _setCookie: setCookie };
    }),

  login: publicProcedure
    .input(
      z.object({
        email: z.string().email(),
        password: z.string().min(1),
      })
    )
    .mutation(async ({ input, ctx: _ctx }) => {
      try {
        const { data, rawResponse } = await apiFetchWithCookies<unknown>(
          "/api/v1/auth/login",
          {
            method: "POST",
            body: JSON.stringify(input),
            headers: { "Content-Type": "application/json" },
          }
        );
        const parsed = AuthResponseSchema.parse(data);
        const setCookie = rawResponse.headers.get("set-cookie");
        return { ...parsed, _setCookie: setCookie };
      } catch (err) {
        throw new TRPCError({
          code: "UNAUTHORIZED",
          message: err instanceof Error ? err.message : "Login failed",
        });
      }
    }),

  logout: publicProcedure.mutation(async ({ ctx }) => {
    await fetch(`${API_URL}/api/v1/auth/logout`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(ctx.cookieHeader ? { cookie: ctx.cookieHeader } : {}),
      },
    });
    return { ok: true };
  }),
});
