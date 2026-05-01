import { NextRequest, NextResponse } from "next/server";

const API_URL =
  process.env.API_URL_INTERNAL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = (await req.json()) as unknown;
  const upstream = await fetch(`${API_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  const data = (await upstream.json()) as unknown;
  const res = NextResponse.json(data, { status: upstream.status });

  // Passthrough Set-Cookie from FastAPI so the browser stores ragp_session
  // headers.get("set-cookie") merges all Set-Cookie values into one comma-
  // joined string and breaks them apart at the embedded commas in expiry
  // dates.  getSetCookie() returns each cookie as its own entry.
  for (const cookie of upstream.headers.getSetCookie()) {
    res.headers.append("set-cookie", cookie);
  }
  return res;
}
