import type { NextRequest } from "next/server";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Context {
  organization_id: string | null;
  /** Raw cookie string forwarded from browser to FastAPI */
  cookieHeader: string | null;
}

/** Build tRPC context from the incoming HTTP request. */
export async function createContext(req: NextRequest): Promise<Context> {
  const cookieHeader = req.headers.get("cookie");

  if (!cookieHeader) {
    return { organization_id: null, cookieHeader };
  }

  try {
    const response = await fetch(`${API_URL}/api/v1/auth/me`, {
      headers: { cookie: cookieHeader },
      cache: "no-store",
    });

    if (!response.ok) {
      return { organization_id: null, cookieHeader };
    }

    const data = (await response.json()) as { organization?: { id?: string | null } | null };
    const organization_id = data.organization?.id ?? null;
    return { organization_id, cookieHeader };
  } catch {
    return { organization_id: null, cookieHeader };
  }
}
