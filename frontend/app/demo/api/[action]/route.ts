import { upstream } from "../../../student/payments/finance-api";

const headers = { "Cache-Control": "no-store" };
const failure = (status: number) => Response.json({ error: "Demo service unavailable" }, { status, headers });

// Fixed upstream paths; the backend still requires a demo-administrator session.
const PATHS: Record<string, string> = {
  reset: "/api/v1/demo/reset",
  "advance-clock": "/api/v1/demo/clock/advance",
  fault: "/api/v1/demo/faults",
  tick: "/api/v1/demo/university/tick",
  document: "/api/v1/demo/documents",
};

export async function POST(request: Request, context: { params: Promise<{ action: string }> }) {
  try {
    const source = new URL(request.headers.get("origin") ?? "");
    if (!["http:", "https:"].includes(source.protocol) || source.host !== request.headers.get("host")
      || request.headers.get("sec-fetch-site") === "cross-site") return failure(403);
  } catch { return failure(403); }
  const { action } = await context.params;
  const path = PATHS[action];
  const base = upstream();
  if (!path) return failure(404);
  if (!base) return failure(503);
  let body: string;
  try {
    body = await request.text();
    if (body.length > 6000) return failure(413);
    JSON.parse(body || "{}");
  } catch { return failure(400); }
  try {
    const response = await fetch(new URL(path, base), {
      method: "POST", redirect: "error", cache: "no-store", signal: AbortSignal.timeout(15000),
      headers: {
        "Content-Type": "application/json",
        Cookie: request.headers.get("cookie") ?? "",
        Origin: request.headers.get("origin") ?? "",
      },
      body: action === "tick" ? undefined : body,
    });
    return new Response(await response.text(), {
      status: response.status, headers: { ...headers, "Content-Type": "application/json" },
    });
  } catch { return failure(502); }
}
