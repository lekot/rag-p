import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type RouteContext = {
  params: { path: string[] };
};

function buildUpstreamUrl(req: NextRequest, path: string[]): string {
  const joined = path.join("/");
  const apiPath = joined.startsWith("api/") ? joined : `api/${joined}`;
  return `${API_URL}/${apiPath}${req.nextUrl.search}`;
}

async function proxy(req: NextRequest, context: RouteContext) {
  const headers: HeadersInit = {};
  const cookie = req.headers.get("cookie");
  const contentType = req.headers.get("content-type");
  const accept = req.headers.get("accept");
  if (cookie) headers.cookie = cookie;
  if (contentType) headers["content-type"] = contentType;
  if (accept) headers.accept = accept;

  const upstream = await fetch(buildUpstreamUrl(req, context.params.path), {
    method: req.method,
    headers,
    body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.arrayBuffer(),
  });

  const responseHeaders = new Headers();
  const upstreamContentType = upstream.headers.get("content-type");
  if (upstreamContentType) responseHeaders.set("content-type", upstreamContentType);
  const setCookie = upstream.headers.get("set-cookie");
  if (setCookie) responseHeaders.set("set-cookie", setCookie);

  return new NextResponse(await upstream.arrayBuffer(), {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export async function GET(req: NextRequest, context: RouteContext) {
  return proxy(req, context);
}

export async function POST(req: NextRequest, context: RouteContext) {
  return proxy(req, context);
}
