import type { NextRequest } from "next/server";

const upstream = process.env.CLOUDOPS_API_URL ?? "http://localhost:8000";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const target = new URL(path.join("/"), `${upstream}/`);
  target.search = request.nextUrl.search;
  const body = request.method === "GET" || request.method === "HEAD" ? undefined : request.body;
  const response = await fetch(target, {
    method: request.method,
    headers: { "Content-Type": request.headers.get("Content-Type") ?? "application/json" },
    body,
    duplex: body ? "half" : undefined,
    cache: "no-store",
  } as RequestInit & { duplex?: "half" });
  const headers = new Headers(response.headers);
  headers.delete("content-encoding");
  headers.delete("content-length");
  return new Response(response.body, { status: response.status, headers });
}

export const GET = proxy;
export const POST = proxy;
