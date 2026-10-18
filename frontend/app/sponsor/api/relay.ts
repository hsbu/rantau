import type { components } from "../../../lib/api-contracts/generated";

type ApprovalView = components["schemas"]["ApprovalView"];
type SessionSummary = components["schemas"]["SessionSummary"];
type DecisionResult = components["schemas"]["SponsorDecisionResult"];
type Currency = components["schemas"]["Currency"];
type ApprovalState = components["schemas"]["ApprovalState"];
type SecurityCase = components["schemas"]["SecurityCaseView"];

type Operation =
  | "login"
  | "session"
  | "logout"
  | "approvals"
  | "cases"
  | { kind: "decision"; approvalId: string };

const noStore = { "Cache-Control": "no-store" };
const identifier = /^[A-Za-z0-9_.:-]{1,128}$/;
const digest = /^[0-9a-f]{64}$/;
const states = new Set<ApprovalState>([
  "REQUESTED", "PENDING", "APPROVED", "REJECTED", "EXPIRED", "REVOKED",
  "INVALIDATED_BY_CHANGE", "CONSUMED",
]);
const currencies = new Set<Currency>(["IDR", "CNY"]);
const caseStates = new Set<SecurityCase["state"]>([
  "OPEN", "UNDER_REVIEW", "RESOLVED", "ESCALATED",
]);
const caseReasons = new Set<SecurityCase["reason"]>([
  "UNKNOWN_BENEFICIARY", "BENEFICIARY_MISMATCH", "BENEFICIARY_CHANGE_REQUESTED",
  "PROMPT_INJECTION", "SCAM_INDICATOR", "POLICY_REVIEW",
]);
const roles = new Set<SessionSummary["role"]>([
  "STUDENT", "SPONSOR", "UNIVERSITY_SERVICE", "DEMO_ADMIN",
]);

function failure(status: number, code: string, retryAfter?: string): Response {
  const headers = new Headers(noStore);
  if (retryAfter && /^\d{1,4}$/.test(retryAfter)) headers.set("Retry-After", retryAfter);
  return Response.json({ code }, { status, headers });
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, expected: string[]): boolean {
  return Object.keys(value).length === expected.length
    && expected.every(key => Object.hasOwn(value, key));
}

function validSession(value: unknown): value is SessionSummary {
  return record(value) && exactKeys(value, ["authenticated", "role"])
    && value.authenticated === true && typeof value.role === "string"
    && roles.has(value.role as SessionSummary["role"]);
}

function validAmount(value: unknown, positive = false): value is number {
  return typeof value === "number" && Number.isSafeInteger(value)
    && (positive ? value > 0 : value >= 0);
}

function validApproval(value: unknown): value is ApprovalView {
  if (!record(value) || !exactKeys(value, [
    "source_label", "beneficiary_label", "source_principal_minor", "fee_minor", "approval_id",
    "intent_id", "intent_revision", "terms_hash", "state", "expires_at", "purpose",
    "source_currency", "destination_currency", "source_total_minor", "destination_amount_minor",
    "simulated",
  ])) return false;
  return typeof value.source_label === "string" && value.source_label.length > 0
    && value.source_label.length <= 120 && typeof value.beneficiary_label === "string"
    && value.beneficiary_label.length > 0 && value.beneficiary_label.length <= 120
    && validAmount(value.source_principal_minor) && validAmount(value.fee_minor)
    && typeof value.approval_id === "string" && identifier.test(value.approval_id)
    && typeof value.intent_id === "string" && identifier.test(value.intent_id)
    && validAmount(value.intent_revision, true) && digest.test(String(value.terms_hash))
    && typeof value.state === "string" && states.has(value.state as ApprovalState)
    && typeof value.expires_at === "string" && Number.isFinite(Date.parse(value.expires_at))
    && (value.purpose === "TUITION" || value.purpose === "ALLOWANCE")
    && typeof value.source_currency === "string" && currencies.has(value.source_currency as Currency)
    && typeof value.destination_currency === "string"
    && currencies.has(value.destination_currency as Currency)
    && validAmount(value.source_total_minor, true)
    && validAmount(value.destination_amount_minor, true)
    && value.simulated === true;
}

function validApprovalList(value: unknown): value is ApprovalView[] {
  return Array.isArray(value) && value.length <= 100 && value.every(validApproval);
}

function validDecisionResult(value: unknown): value is DecisionResult {
  return record(value) && exactKeys(value, [
    "approval_id", "decision", "intent_id", "current_terms_hash", "recorded_at",
  ]) && typeof value.approval_id === "string" && identifier.test(value.approval_id)
    && (value.decision === "APPROVED" || value.decision === "REJECTED")
    && typeof value.intent_id === "string" && identifier.test(value.intent_id)
    && typeof value.current_terms_hash === "string" && digest.test(value.current_terms_hash)
    && typeof value.recorded_at === "string" && Number.isFinite(Date.parse(value.recorded_at));
}

function validCase(value: unknown): value is SecurityCase {
  if (!record(value) || !exactKeys(value, [
    "case_id", "resource_id", "state", "reason", "created_at", "updated_at", "audit_event_id",
  ])) return false;
  return typeof value.case_id === "string" && identifier.test(value.case_id)
    && typeof value.resource_id === "string" && identifier.test(value.resource_id)
    && typeof value.state === "string" && caseStates.has(value.state as SecurityCase["state"])
    && typeof value.reason === "string" && caseReasons.has(value.reason as SecurityCase["reason"])
    && typeof value.created_at === "string" && Number.isFinite(Date.parse(value.created_at))
    && typeof value.updated_at === "string" && Number.isFinite(Date.parse(value.updated_at))
    && typeof value.audit_event_id === "string" && identifier.test(value.audit_event_id);
}

function validCaseList(value: unknown): value is { cases: SecurityCase[] } {
  return record(value) && exactKeys(value, ["cases"]) && Array.isArray(value.cases)
    && value.cases.length <= 100 && value.cases.every(validCase);
}

async function requestBody(request: Request, operation: Operation): Promise<string | null> {
  const text = await readLimited(request.body, 4096);
  if (text === null) return null;
  if (operation === "logout") return text.length === 0 ? "" : null;
  let value: unknown;
  try { value = JSON.parse(text); } catch { return null; }
  if (!record(value)) return null;
  if (operation === "login") {
    if (!exactKeys(value, ["username", "password"])
      || typeof value.username !== "string" || !/^[a-z0-9_.-]{1,64}$/.test(value.username)
      || typeof value.password !== "string" || value.password.length < 1
      || value.password.length > 128) return null;
    return JSON.stringify({ username: value.username, password: value.password });
  }
  if (typeof operation === "object") {
    if (!exactKeys(value, ["decision", "terms_hash"])
      || (value.decision !== "APPROVED" && value.decision !== "REJECTED")
      || typeof value.terms_hash !== "string" || !digest.test(value.terms_hash)) return null;
    return JSON.stringify({ decision: value.decision, terms_hash: value.terms_hash });
  }
  return null;
}

async function readLimited(stream: ReadableStream<Uint8Array> | null, maxBytes: number): Promise<string | null> {
  if (!stream) return "";
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) {
        await reader.cancel();
        return null;
      }
      chunks.push(value);
    }
    const body = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      body.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return new TextDecoder("utf-8", { fatal: true }).decode(body);
  } catch {
    return null;
  } finally {
    reader.releaseLock();
  }
}

function trustedOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  const host = request.headers.get("host")?.toLowerCase();
  if (!origin || !host || request.headers.get("sec-fetch-site") === "cross-site") return false;
  try {
    const source = new URL(origin);
    return (source.protocol === "http:" || source.protocol === "https:")
      && source.origin === origin && source.host.toLowerCase() === host;
  } catch { return false; }
}

function sessionCookie(request: Request): string | undefined {
  const raw = request.headers.get("cookie") ?? "";
  if (new TextEncoder().encode(raw).byteLength > 8192) return undefined;
  const matches = raw.split(";").map(part => part.trim()).filter(part => part.startsWith("session="));
  if (matches.length !== 1) return undefined;
  const token = matches[0].slice("session=".length);
  return /^[A-Za-z0-9_-]{43}$/.test(token) ? `session=${token}` : undefined;
}

function validSetCookie(value: string, request: Request, clearing: boolean): boolean {
  const parts = value.split(";").map(part => part.trim());
  const first = parts.shift() ?? "";
  const cookieValue = first.match(/^session=(.*)$/i)?.[1];
  if (cookieValue === undefined || parts.some(part => /^domain=/i.test(part))) return false;
  const attributes = parts.map(part => part.toLowerCase());
  if (!attributes.includes("httponly") || !attributes.includes("path=/")
    || !attributes.some(part => part === "samesite=strict")) return false;
  const origin = request.headers.get("origin") ?? "";
  if (origin.startsWith("https://") && !attributes.includes("secure")) return false;
  if (clearing) {
    const maxAge = attributes.find(part => part.startsWith("max-age="));
    const expires = parts.find(part => /^expires=/i.test(part))?.slice("expires=".length);
    return (cookieValue === "\"\"" || cookieValue === "")
      && (maxAge === "max-age=0" || (expires !== undefined && Date.parse(expires) <= Date.now()));
  }
  return /^[A-Za-z0-9_-]{43}$/.test(cookieValue)
    && attributes.some(part => part === "max-age=3600");
}

function endpoint(operation: Operation): { path: string; method: "GET" | "POST"; cookie: boolean } | null {
  if (operation === "login") return { path: "/api/v1/auth/login", method: "POST", cookie: false };
  if (operation === "session") return { path: "/api/v1/auth/session", method: "GET", cookie: true };
  if (operation === "logout") return { path: "/api/v1/auth/logout", method: "POST", cookie: true };
  if (operation === "approvals") return { path: "/api/v1/sponsor/approvals", method: "GET", cookie: true };
  if (operation === "cases") return { path: "/api/v1/security-cases", method: "GET", cookie: true };
  if (typeof operation === "object" && operation.approvalId !== "." && operation.approvalId !== ".."
    && identifier.test(operation.approvalId)) {
    return {
      path: `/api/v1/sponsor/approvals/${encodeURIComponent(operation.approvalId)}/decision`,
      method: "POST",
      cookie: true,
    };
  }
  return null;
}

function safeUpstreamError(response: Response): Response {
  const errors: Record<number, [number, string]> = {
    400: [400, "INVALID_REQUEST"], 401: [401, "AUTHENTICATION_REQUIRED"],
    403: [403, "REQUEST_FORBIDDEN"], 404: [404, "RESOURCE_UNAVAILABLE"],
    409: [409, "AUTHORITY_CONFLICT"], 413: [413, "INVALID_REQUEST"],
    422: [422, "INVALID_REQUEST"], 429: [429, "LOGIN_THROTTLED"],
    503: [503, "SERVICE_UNAVAILABLE"],
  };
  const [status, code] = errors[response.status] ?? [502, "SERVICE_UNAVAILABLE"];
  return failure(status, code, response.headers.get("retry-after") ?? undefined);
}

export async function relay(request: Request, operation: Operation): Promise<Response> {
  const route = endpoint(operation);
  if (!route) return failure(400, "INVALID_REQUEST");
  if (request.method !== route.method) return failure(405, "METHOD_NOT_ALLOWED");
  const mutating = route.method === "POST";
  if (mutating && !trustedOrigin(request)) return failure(403, "UNTRUSTED_ORIGIN");
  const body = mutating ? await requestBody(request, operation) : undefined;
  if (mutating && body === null) return failure(422, "INVALID_REQUEST");

  const configuredOrigin = process.env.AGENT_API_ORIGIN;
  if (!configuredOrigin) return failure(503, "SERVICE_UNAVAILABLE");
  let upstream: URL;
  try {
    upstream = new URL(configuredOrigin);
    if (!["http:", "https:"].includes(upstream.protocol) || upstream.username || upstream.password
      || upstream.pathname !== "/" || upstream.search || upstream.hash) {
      return failure(503, "SERVICE_UNAVAILABLE");
    }
  } catch { return failure(503, "SERVICE_UNAVAILABLE"); }

  const headers = new Headers();
  if (body && route.method === "POST") headers.set("Content-Type", "application/json");
  if (mutating) {
    headers.set("Origin", request.headers.get("origin")!);
    const fetchSite = request.headers.get("sec-fetch-site");
    if (fetchSite) headers.set("Sec-Fetch-Site", fetchSite);
  }
  if (route.cookie) {
    const cookie = sessionCookie(request);
    if (cookie) headers.set("Cookie", cookie);
  }

  let response: Response;
  try {
    response = await fetch(new URL(route.path, upstream), {
      method: route.method,
      headers,
      ...(body ? { body } : {}),
      redirect: "error",
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    });
  } catch { return failure(502, "SERVICE_UNAVAILABLE"); }

  if (!response.ok) return safeUpstreamError(response);
  if (operation === "logout") {
    if (response.status !== 204) return failure(502, "INVALID_BACKEND_RESPONSE");
    const result = new Response(null, { status: 204, headers: noStore });
    const cookie = response.headers.get("set-cookie");
    if (!cookie || !validSetCookie(cookie, request, true)) {
      return failure(502, "INVALID_BACKEND_RESPONSE");
    }
    result.headers.append("Set-Cookie", cookie);
    return result;
  }
  if (response.status !== 200) return failure(502, "INVALID_BACKEND_RESPONSE");

  let value: unknown;
  try {
    const text = await readLimited(response.body, 65536);
    if (text === null) return failure(502, "INVALID_BACKEND_RESPONSE");
    value = JSON.parse(text);
  } catch { return failure(502, "INVALID_BACKEND_RESPONSE"); }

  let valid = false;
  if (operation === "login" || operation === "session") valid = validSession(value);
  else if (operation === "approvals") valid = validApprovalList(value);
  else if (operation === "cases") valid = validCaseList(value);
  else if (typeof operation === "object") valid = validDecisionResult(value);
  if (!valid) return failure(502, "INVALID_BACKEND_RESPONSE");

  const result = Response.json(value, { headers: noStore });
  if (operation === "login") {
    const cookie = response.headers.get("set-cookie");
    if (!cookie || !validSetCookie(cookie, request, false)) {
      return failure(502, "INVALID_BACKEND_RESPONSE");
    }
    result.headers.append("Set-Cookie", cookie);
  }
  return result;
}
