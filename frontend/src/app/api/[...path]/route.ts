import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const HOP_BY_HOP = new Set([
  "host",
  "connection",
  "content-length",
  "transfer-encoding",
  "keep-alive",
]);

function backendBase(): string | null {
  const raw = (
    process.env.BACKEND_URL ||
    process.env.VITE_API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    process.env.NEXT_PUBLIC_VITE_API_URL ||
    ""
  )
    .trim()
    .replace(/\/$/, "");
  if (!raw || /localhost|127\.0\.0\.1/.test(raw)) return null;
  if (!/^https?:\/\//.test(raw)) return null;
  return raw;
}

async function proxy(request: NextRequest, path: string[]) {
  const base = backendBase();
  if (!base) {
    return NextResponse.json(
      {
        detail:
          "API proxy is not configured. Set BACKEND_URL or VITE_API_URL to the public API origin and redeploy.",
      },
      { status: 503 }
    );
  }

  const target = `${base}/api/${path.join("/")}${request.nextUrl.search}`;
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers.set(key, value);
  });

  const init: RequestInit = { method: request.method, headers, redirect: "manual" };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  try {
    const upstream = await fetch(target, { ...init, signal: AbortSignal.timeout(25000) });
    const out = new Headers();
    upstream.headers.forEach((value, key) => {
      if (!HOP_BY_HOP.has(key.toLowerCase())) out.set(key, value);
    });
    return new NextResponse(upstream.body, { status: upstream.status, headers: out });
  } catch {
    return NextResponse.json(
      { detail: "No se pudo contactar el backend. Si el servicio está dormido, reintentá en unos segundos." },
      { status: 502 }
    );
  }
}

type Ctx = { params: Promise<{ path: string[] }> };

async function handle(request: NextRequest, context: Ctx) {
  const { path } = await context.params;
  return proxy(request, path);
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
export const HEAD = handle;
export const OPTIONS = handle;
