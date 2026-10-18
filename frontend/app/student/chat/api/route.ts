import type { AgentMessage } from "../chat-types";
import { parseAgentResponse } from "../chat-types";

const headers = { "Cache-Control": "no-store" };
const failure = (status: number) => Response.json({ error: "Agent service unavailable" }, { status, headers });

// One fixed upstream path. No actor, role, bearer token or arbitrary URL is accepted.
export async function POST(request: Request) {
  // Next's internal request URL can use localhost behind its standalone server.
  // Compare the browser Origin with the received Host, never a forwarded host header.
  try {
    const source = new URL(request.headers.get("origin") ?? "");
    if (!["http:", "https:"].includes(source.protocol)
      || source.host !== request.headers.get("host")
      || request.headers.get("sec-fetch-site") === "cross-site") return failure(403);
  } catch { return failure(403); }
  let body: AgentMessage;
  try {
    const raw = await request.text();
    if (raw.length > 30000) return failure(413);
    const value = JSON.parse(raw);
    if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).some(key => !["message", "conversation_id"].includes(key))
      || typeof value.message !== "string" || !value.message.trim() || value.message.length > 4000
      || typeof value.conversation_id !== "string"
      || !/^[A-Za-z0-9_.:-]{1,128}$/.test(value.conversation_id)) return failure(400);
    body = { message: value.message, conversation_id: value.conversation_id };
  } catch { return failure(400); }

  const origin = process.env.AGENT_API_ORIGIN;
  if (!origin) return failure(503);
  try {
    const upstream = new URL(origin);
    if (!["http:", "https:"].includes(upstream.protocol) || upstream.username || upstream.password
      || upstream.pathname !== "/" || upstream.search || upstream.hash) return failure(503);
    const response = await fetch(new URL("/api/v1/agent/messages", upstream), {
      method: "POST", redirect: "error", cache: "no-store", signal: AbortSignal.timeout(25000),
      headers: {
        "Content-Type": "application/json", Cookie: request.headers.get("cookie") ?? "",
        Origin: request.headers.get("origin") ?? "",
      },
      body: JSON.stringify(body),
    });
    if (!response.ok) return failure([401, 403, 404, 422, 503].includes(response.status) ? response.status : 502);
    return Response.json(parseAgentResponse(await response.json()), { headers });
  } catch { return failure(502); }
}
