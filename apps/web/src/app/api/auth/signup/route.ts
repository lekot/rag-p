import { NextRequest, NextResponse } from "next/server";

// Server-side fetch: prefer the docker-internal URL (e.g. http://api:8000)
// over the public domain so the request stays inside the compose network and
// doesn't loop back through Caddy.
const API_URL =
  process.env.API_URL_INTERNAL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = (await req.json()) as unknown;
  const upstream = await fetch(`${API_URL}/api/v1/auth/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  const data = (await upstream.json()) as unknown;
  const res = NextResponse.json(data, { status: upstream.status });

  // Passthrough Set-Cookie from FastAPI so the browser stores ragp_session.
  // `headers.get("set-cookie")` only returns one concatenated string with all
  // cookies joined by ", " — Set-Cookie values themselves contain commas
  // (e.g. expiry dates), so re-emitting that breaks the cookie.  Use the
  // Node 20+ `getSetCookie()` API and append each entry separately.
  for (const cookie of upstream.headers.getSetCookie()) {
    res.headers.append("set-cookie", cookie);
  }
  return res;
}
