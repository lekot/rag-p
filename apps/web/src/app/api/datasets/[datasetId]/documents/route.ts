import { NextRequest, NextResponse } from "next/server";

const API_URL =
  process.env.API_URL_INTERNAL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

export async function POST(
  req: NextRequest,
  { params }: { params: { datasetId: string } }
) {
  const formData = await req.formData();
  const upstream = await fetch(`${API_URL}/api/v1/datasets/${params.datasetId}/documents`, {
    method: "POST",
    headers: { cookie: req.headers.get("cookie") ?? "" },
    body: formData,
  });

  const contentType = upstream.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return NextResponse.json(await upstream.json(), { status: upstream.status });
  }

  return new NextResponse(await upstream.text(), {
    status: upstream.status,
    headers: { "content-type": contentType || "text/plain" },
  });
}
