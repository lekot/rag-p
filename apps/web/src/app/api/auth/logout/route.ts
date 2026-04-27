import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const cookieHeader = req.headers.get("cookie");
  await fetch(`${API_URL}/api/v1/auth/logout`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(cookieHeader ? { cookie: cookieHeader } : {}),
    },
  });

  const res = NextResponse.json({ ok: true }, { status: 200 });
  // Clear the session cookie
  res.cookies.delete("ragp_session");
  return res;
}
