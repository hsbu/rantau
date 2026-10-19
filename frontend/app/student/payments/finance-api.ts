import { cookies } from "next/headers";
import type { components } from "../../../lib/api-contracts/generated";

export type Schema = components["schemas"];

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; reason: "signin" | "unavailable" | "missing" | "refused"; error?: Schema["DomainError"] };

function upstream(): URL | null {
  const origin = process.env.FINANCE_API_ORIGIN ?? process.env.AGENT_API_ORIGIN;
  if (!origin) return null;
  try {
    const url = new URL(origin);
    const safe = ["http:", "https:"].includes(url.protocol) && !url.username && !url.password
      && url.pathname === "/" && !url.search && !url.hash;
    return safe ? url : null;
  } catch {
    return null;
  }
}

// Server-only read. The browser session cookie is forwarded; no identity is ever supplied here.
export async function financeGet<T>(path: string): Promise<ApiResult<T>> {
  const base = upstream();
  if (!base) return { ok: false, reason: "unavailable" };
  try {
    const response = await fetch(new URL(path, base), {
      cache: "no-store", redirect: "error", signal: AbortSignal.timeout(10000),
      headers: { Cookie: (await cookies()).toString() },
    });
    return interpret<T>(response);
  } catch {
    return { ok: false, reason: "unavailable" };
  }
}

export async function interpret<T>(response: Response): Promise<ApiResult<T>> {
  if (response.status === 401) return { ok: false, reason: "signin" };
  if (response.status === 404 || response.status === 403) {
    const body = await response.json().catch(() => null);
    if (body && typeof body === "object" && "reason_code" in body) {
      return { ok: false, reason: "refused", error: body as Schema["DomainError"] };
    }
    return { ok: false, reason: "missing" };
  }
  if (response.status === 409 || response.status === 422) {
    const body = await response.json().catch(() => null);
    return { ok: false, reason: "refused", error: body as Schema["DomainError"] };
  }
  if (!response.ok) return { ok: false, reason: "unavailable" };
  return { ok: true, data: (response.status === 204 ? undefined : await response.json()) as T };
}

// A Response with a null-body status (204) must not be constructed with a body, even an empty one.
const NULL_BODY_STATUSES = new Set([204, 205, 304]);

export async function relayResponse(response: Response, headers: Record<string, string>): Promise<Response> {
  const body = NULL_BODY_STATUSES.has(response.status) ? null : await response.text();
  return new Response(body, { status: response.status, headers: { ...headers, "Content-Type": "application/json" } });
}

export { upstream };
