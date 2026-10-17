import { upstream } from "../../finance-api";

const headers = { "Cache-Control": "no-store" };
const failure = (status: number) => Response.json({ error: "Finance service unavailable" }, { status, headers });
const ID = /^[A-Za-z0-9_.:-]{1,128}$/;

// Fixed upstream paths only. No actor, role or arbitrary URL is ever accepted from the browser.
type Target = { path: string; payload?: object; headers?: Record<string, string> };
const ACTIONS: Record<string, (body: Record<string, string>) => Target | null> = {
  "cancel-intent": b => ID.test(b.id ?? "") ? { path: `/api/v1/payment-intents/${b.id}/cancel` } : null,
  // The key is derived server-side from the intent so a retry can never become a second payment.
  "execute-intent": b => ID.test(b.id ?? "")
    ? { path: `/api/v1/payment-intents/${b.id}/execute`, headers: { "Idempotency-Key": `exec-${b.id}` } }
    : null,
  "recheck-obligation": b => ID.test(b.id ?? "") ? { path: `/api/v1/tuition/obligations/${b.id}/recheck` } : null,
  "recheck-transfer": b => ID.test(b.id ?? "") ? { path: `/api/v1/transfers/${b.id}/recheck` } : null,
  "submit-case": b => ID.test(b.id ?? "") ? { path: `/api/v1/reconciliations/${b.id}/submit` } : null,
  "open-case": b => ID.test(b.transfer_id ?? "") && ID.test(b.obligation_id ?? "")
    ? { path: "/api/v1/reconciliations", payload: { payment_id: b.transfer_id, obligation_id: b.obligation_id, evidence_ids: [] } }
    : null,
};

export async function POST(request: Request, context: { params: Promise<{ action: string }> }) {
  try {
    const source = new URL(request.headers.get("origin") ?? "");
    if (!["http:", "https:"].includes(source.protocol) || source.host !== request.headers.get("host")
      || request.headers.get("sec-fetch-site") === "cross-site") return failure(403);
  } catch { return failure(403); }
  const { action } = await context.params;
  const build = ACTIONS[action];
  if (!build) return failure(404);
  let body: Record<string, string>;
  try {
    const raw = await request.text();
    if (raw.length > 2000) return failure(413);
    const value = JSON.parse(raw);
    if (!value || typeof value !== "object" || Array.isArray(value)) return failure(400);
    body = value;
  } catch { return failure(400); }
  const target = build(body);
  const base = upstream();
  if (!target || !base) return failure(target ? 503 : 400);
  try {
    const response = await fetch(new URL(target.path, base), {
      method: "POST", redirect: "error", cache: "no-store", signal: AbortSignal.timeout(15000),
      headers: {
        "Content-Type": "application/json",
        Cookie: request.headers.get("cookie") ?? "",
        Origin: request.headers.get("origin") ?? "",
        ...target.headers,
      },
      body: target.payload ? JSON.stringify(target.payload) : undefined,
    });
    const text = await response.text();
    return new Response(text, { status: response.status, headers: { ...headers, "Content-Type": "application/json" } });
  } catch { return failure(502); }
}
