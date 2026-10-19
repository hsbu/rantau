import { parseDetailSnapshot } from "../../detail-types";

const headers = { "Cache-Control": "no-store" };
const failure = (status: number) => Response.json({ error: "Chat details unavailable" }, { status, headers });

export async function GET(request: Request) {
  const url = new URL(request.url);
  const source = request.headers.get("origin");
  if (request.headers.get("sec-fetch-site") === "cross-site") return failure(403);
  if (source) {
    try {
      const parsed = new URL(source);
      if (!["http:", "https:"].includes(parsed.protocol) || parsed.host !== request.headers.get("host")) return failure(403);
    } catch { return failure(403); }
  }
  const conversation = url.searchParams.get("conversation_id");
  const run = url.searchParams.get("run_id");
  if ([...url.searchParams.keys()].some(k => !["conversation_id", "run_id"].includes(k))
    || url.searchParams.getAll("conversation_id").length !== 1 || url.searchParams.getAll("run_id").length !== 1
    || !conversation || !run || !/^[A-Za-z0-9_.:-]{1,128}$/.test(conversation)
    || [".", ".."].includes(conversation) || !/^[A-Za-z0-9_.:-]{1,128}$/.test(run)) return failure(400);
  try {
    const origin = new URL(process.env.AGENT_API_ORIGIN ?? "");
    if (!["http:", "https:"].includes(origin.protocol) || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash) return failure(503);
    const upstream = new URL(`/api/v1/agent/conversations/${encodeURIComponent(conversation)}/details`, origin);
    upstream.searchParams.set("run_id", run);
    const response = await fetch(upstream, { method: "GET", redirect: "error", cache: "no-store", signal: AbortSignal.timeout(5000),
      headers: { Cookie: request.headers.get("cookie") ?? "" } });
    if (!response.ok) return failure([401, 403, 404, 422, 503].includes(response.status) ? response.status : 502);
    const reader = response.body?.getReader();
    if (!reader) return failure(502);
    const chunks: Uint8Array[] = [];
    let bytes = 0;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > 16000) { await reader.cancel(); return failure(502); }
      chunks.push(value);
    }
    const buffer = new Uint8Array(bytes);
    let offset = 0;
    for (const chunk of chunks) { buffer.set(chunk, offset); offset += chunk.byteLength; }
    const raw = new TextDecoder("utf-8", { fatal: true }).decode(buffer);
    return Response.json(parseDetailSnapshot(JSON.parse(raw), run), { headers });
  } catch { return failure(502); }
}
