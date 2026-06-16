import { NextRequest, NextResponse } from "next/server";

// 서버 사이드 호출 전용 — Node.js fetch는 Windows에서 localhost를 IPv6(::1)로 해석할 수 있어
// uvicorn(0.0.0.0, IPv4)과 충돌함. 127.0.0.1로 명시.
const BACKEND = process.env.INTERNAL_API_URL ?? "http://127.0.0.1:8000";
const SECRET = process.env.API_SECRET ?? "";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
): Promise<NextResponse> {
  const { path } = await params;
  const backendPath = "/" + path.join("/");

  const url = new URL(req.url);
  const search = url.search;

  const body = await req.text();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (SECRET) headers["Authorization"] = `Bearer ${SECRET}`;

  try {
    const res = await fetch(`${BACKEND}${backendPath}${search}`, {
      method: "POST",
      headers,
      body: body || undefined,
      cache: "no-store",
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json({ ok: false, message: String(e) }, { status: 502 });
  }
}
