import { NextRequest, NextResponse } from "next/server";

const PUBLIC_PATHS = [
  "/login",
  "/signup",
  "/docs",
  "/invite",
  "/_next",
  "/api",
  "/favicon.ico",
  "/pricing",
  "/terms",
  "/contacts",
  "/delivery",
];

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  process.env.RAG_API_INTERNAL_URL ||
  "https://api.lekottt.ru";

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  const session = req.cookies.get("ragp_session");

  const goLogin = () => {
    const loginUrl = req.nextUrl.clone();
    loginUrl.pathname = "/login";
    loginUrl.search = "";
    return NextResponse.redirect(loginUrl);
  };

  if (!session) {
    return goLogin();
  }

  // Validate the session by hitting the FastAPI /me endpoint with the cookie.
  // If the session is expired or revoked, the cookie is present but server returns 401.
  try {
    const meResp = await fetch(`${API_BASE}/api/v1/auth/me`, {
      headers: {
        cookie: `ragp_session=${session.value}`,
      },
      cache: "no-store",
    });
    if (!meResp.ok) {
      return goLogin();
    }
  } catch {
    // API unreachable — let the request through; client-side useUser will catch up.
    return NextResponse.next();
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
