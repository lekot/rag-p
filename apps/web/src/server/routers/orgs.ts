import { z } from "zod";
import { TRPCError } from "@trpc/server";
import { router, protectedProcedure } from "../trpc";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Schemas ──────────────────────────────────────────────────────────────────

const MemberSchema = z.object({
  user_id: z.string(),
  email: z.string(),
  role: z.string(),
  created_at: z.string(),
});
export type Member = z.infer<typeof MemberSchema>;

const InviteSchema = z.object({
  id: z.string(),
  email: z.string(),
  role: z.string(),
  created_at: z.string(),
  expires_at: z.string(),
  accepted_at: z.string().nullable(),
});
export type Invite = z.infer<typeof InviteSchema>;

const InviteCreatedSchema = z.object({
  id: z.string(),
  invite_url: z.string(),
});
export type InviteCreated = z.infer<typeof InviteCreatedSchema>;

const RoleEnum = z.enum(["owner", "admin", "member"]);
const InviteRoleEnum = z.enum(["admin", "member"]);

// ── Helpers ──────────────────────────────────────────────────────────────────

async function authedFetch(
  path: string,
  cookieHeader: string,
  options?: RequestInit
): Promise<Response> {
  return fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      cookie: cookieHeader,
      ...options?.headers,
    },
  });
}

async function readError(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { detail?: string };
    return data.detail ?? `API ${res.status}`;
  } catch {
    return `API ${res.status}`;
  }
}

function toTRPCError(res: Response, message: string): TRPCError {
  if (res.status === 401) return new TRPCError({ code: "UNAUTHORIZED", message });
  if (res.status === 403) return new TRPCError({ code: "FORBIDDEN", message });
  if (res.status === 404) return new TRPCError({ code: "NOT_FOUND", message });
  if (res.status === 409) return new TRPCError({ code: "CONFLICT", message });
  if (res.status === 400 || res.status === 422)
    return new TRPCError({ code: "BAD_REQUEST", message });
  return new TRPCError({ code: "INTERNAL_SERVER_ERROR", message });
}

// ── Router ───────────────────────────────────────────────────────────────────

export const orgsRouter = router({
  listMembers: protectedProcedure.query(async ({ ctx }) => {
    const res = await authedFetch(
      `/api/v1/orgs/${ctx.organization_id}/members`,
      ctx.cookieHeader as string
    );
    if (!res.ok) throw toTRPCError(res, await readError(res));
    const data = (await res.json()) as unknown;
    return { members: z.array(MemberSchema).parse(data) };
  }),

  listInvites: protectedProcedure.query(async ({ ctx }) => {
    const res = await authedFetch(
      `/api/v1/orgs/${ctx.organization_id}/invites`,
      ctx.cookieHeader as string
    );
    // Members without admin/owner role get 403 — return empty list rather than throw.
    if (res.status === 403) return { invites: [] as Invite[] };
    if (!res.ok) throw toTRPCError(res, await readError(res));
    const data = (await res.json()) as unknown;
    return { invites: z.array(InviteSchema).parse(data) };
  }),

  invite: protectedProcedure
    .input(
      z.object({
        email: z.string().email(),
        role: InviteRoleEnum,
      })
    )
    .mutation(async ({ input, ctx }) => {
      const res = await authedFetch(
        `/api/v1/orgs/${ctx.organization_id}/invites`,
        ctx.cookieHeader as string,
        {
          method: "POST",
          body: JSON.stringify({ email: input.email, role: input.role }),
        }
      );
      if (!res.ok) throw toTRPCError(res, await readError(res));
      const data = (await res.json()) as unknown;
      return InviteCreatedSchema.parse(data);
    }),

  revokeInvite: protectedProcedure
    .input(z.object({ id: z.string() }))
    .mutation(async ({ input, ctx }) => {
      const res = await authedFetch(
        `/api/v1/orgs/${ctx.organization_id}/invites/${input.id}`,
        ctx.cookieHeader as string,
        { method: "DELETE" }
      );
      if (res.status !== 204 && !res.ok)
        throw toTRPCError(res, await readError(res));
      return { ok: true as const };
    }),

  removeMember: protectedProcedure
    .input(z.object({ user_id: z.string() }))
    .mutation(async ({ input, ctx }) => {
      const res = await authedFetch(
        `/api/v1/orgs/${ctx.organization_id}/members/${input.user_id}`,
        ctx.cookieHeader as string,
        { method: "DELETE" }
      );
      if (res.status !== 204 && !res.ok)
        throw toTRPCError(res, await readError(res));
      return { ok: true as const };
    }),

  changeRole: protectedProcedure
    .input(
      z.object({
        user_id: z.string(),
        role: RoleEnum,
      })
    )
    .mutation(async ({ input, ctx }) => {
      const res = await authedFetch(
        `/api/v1/orgs/${ctx.organization_id}/members/${input.user_id}`,
        ctx.cookieHeader as string,
        {
          method: "PATCH",
          body: JSON.stringify({ role: input.role }),
        }
      );
      if (!res.ok) throw toTRPCError(res, await readError(res));
      const data = (await res.json()) as unknown;
      return MemberSchema.parse(data);
    }),
});
