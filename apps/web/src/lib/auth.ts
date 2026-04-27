"use client";

import { trpc } from "./trpc";
import type { MeResponse } from "@/server/routers/auth";

export type { MeResponse };

/**
 * Returns the current authenticated user + organization, or null if not logged in.
 * Backed by tRPC auth.me which checks the session cookie server-side.
 */
export function useUser(): MeResponse | null | undefined {
  const query = trpc.auth.me.useQuery(undefined, {
    retry: false,
    staleTime: 60_000,
  });
  // undefined = loading, null = not authenticated, MeResponse = authenticated
  if (query.isLoading) return undefined;
  return query.data ?? null;
}
