import { upstream } from "../../finance-api";

const headers = { "Cache-Control": "no-store" };
const failure = (status: number) => Response.json({ error: "Finance service unavailable" }, { status, headers });
const ID = /^[A-Za-z0-9_.:-]{1,128}$/;

// Fixed upstream paths only. No actor, role or arbitrary URL is ever accepted from the browser.
type Target = {
  path: string; payload?: object; headers?: Record<string, string>;
  // A follow-up call built from the first response, e.g. asking the owner to approve a new request.
  after?: (created: unknown) => Target | null;
};
const approvalRequest = (created: unknown): Target | null => {
  const id = (created as { id?: unknown } | null)?.id;
  return typeof id === "string" && ID.test(id)
    ? { path: `/api/v1/payment-intents/${id}/approval-requests` } : null;
};
const proposal = (b: Record<string, string>) =>
  ["obligation_id", "quote_id", "source_account_id", "beneficiary_id"].every(key => ID.test(b[key] ?? ""))
    ? { obligation_id: b.obligation_id, source_account_id: b.source_account_id,
        beneficiary_id: b.beneficiary_id, quote_id: b.quote_id, purpose: "TUITION" }
    : null;
const ACTIONS: Record<string, (body: Record<string, string>) => Target | null> = {
  "owner-decision": b => ID.test(b.id ?? "") && /^[a-f0-9]{64}$/.test(b.terms_hash ?? "")
    && ["APPROVED", "REJECTED"].includes(b.decision)
    && Object.keys(b).every(key => ["id", "decision", "terms_hash"].includes(key))
    ? { path: `/api/v1/student/approvals/${b.id}/decision`, payload: { decision: b.decision, terms_hash: b.terms_hash } } : null,
  "create-intent": b => { const payload = proposal(b);
    return payload ? { path: "/api/v1/payment-intents", payload, after: approvalRequest } : null; },
  "revise-intent": b => { const payload = proposal(b);
    return payload && ID.test(b.id ?? "")
      ? { path: `/api/v1/payment-intents/${b.id}/revisions`, payload, after: approvalRequest } : null; },
  "request-approval": b => ID.test(b.id ?? "") ? approvalRequest({ id: b.id }) : null,
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
  const send = (next: Target) => fetch(new URL(next.path, base), {
    method: "POST", redirect: "error", cache: "no-store", signal: AbortSignal.timeout(15000),
    headers: {
      "Content-Type": "application/json",
      Cookie: request.headers.get("cookie") ?? "",
      Origin: request.headers.get("origin") ?? "",
      ...next.headers,
    },
    body: next.payload ? JSON.stringify(next.payload) : undefined,
  });
  const relay = async (response: Response) => new Response(await response.text(), {
    status: response.status, headers: { ...headers, "Content-Type": "application/json" },
  });
  try {
    const first = await send(target);
    const followUp = first.ok && target.after ? target.after(await first.clone().json().catch(() => null)) : null;
    if (!followUp) return await relay(first);
    const second = await send(followUp);
    return await relay(second.ok ? first : second);
  } catch { return failure(502); }
}
