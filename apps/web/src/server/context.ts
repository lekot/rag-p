import type { NextRequest } from "next/server";

export interface Context {
  organization_id: string;
  /** Raw cookie string forwarded from browser to FastAPI */
  cookieHeader: string | null;
}

/** Build tRPC context from the incoming HTTP request. */
export function createContext(req: NextRequest): Context {
  // TODO: replace with Clerk auth.organizationId in production
  const organization_id =
    req.headers.get("x-organization-id") ??
    process.env.NEXT_PUBLIC_ORG_ID ??
    "00000000-0000-0000-0000-000000000001";
  const cookieHeader = req.headers.get("cookie");
  return { organization_id, cookieHeader };
}
