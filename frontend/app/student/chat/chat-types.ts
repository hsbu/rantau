import type { components } from "../../../lib/api-contracts/generated";

export type Schema = components["schemas"];
export type AgentMessage = Schema["AgentMessage"];
export type AgentResponse = Schema["AgentResponse"];

// Presentation data assembled by a trusted adapter, never parsed from assistant prose.
export type ActionSummary = {
  obligation: Schema["TuitionObligation"];
  quote?: Schema["FxQuote"];
  approval?: Schema["ApprovalRequest"];
  payment?: Schema["PaymentResult"];
  case?: Schema["ReconciliationCase"];
  issue?: Schema["DomainError"];
  beneficiary: string;
  funding: string;
  asOf: string;
};
export type ChatTurn = { response: AgentResponse; summary?: ActionSummary };
export interface ChatTransport {
  send(body: AgentMessage, signal: AbortSignal): Promise<ChatTurn>;
  reset?(): void;
}

export class ChatError extends Error {
  constructor(public readonly kind: "session" | "unavailable" | "invalid" | "uncertain") {
    super(kind);
  }
}

export function parseAgentResponse(value: unknown): AgentResponse {
  if (!value || typeof value !== "object") throw new ChatError("invalid");
  const item = value as Record<string, unknown>;
  const intents = ["ASK_POLICY", "TUITION", "ALLOWANCE", "TRACK", "RECOVER", "VERIFY_MESSAGE"];
  if (typeof item.run_id !== "string" || !/^[A-Za-z0-9_.:-]{1,128}$/.test(item.run_id)
    || typeof item.message !== "string" || !item.message.trim() || item.message.length > 24000
    || (item.requested_action !== null && !intents.includes(String(item.requested_action)))
    || !Array.isArray(item.tool_events) || item.tool_events.length > 100
    || !item.tool_events.every(event => event && typeof event === "object"
      && typeof event.tool === "string" && ["OK", "PENDING", "UNAVAILABLE", "DENIED"].includes(event.status))
    || !Array.isArray(item.resources) || item.resources.length > 100
    || !item.resources.every(ref => ref && typeof ref === "object"
      && ["obligation", "payment", "case", "policy"].includes(ref.kind)
      && typeof ref.id === "string" && /^[A-Za-z0-9_.:-]{1,128}$/.test(ref.id))) {
    throw new ChatError("invalid");
  }
  return value as AgentResponse;
}

export const connectedTransport: ChatTransport = {
  async send(body, signal) {
    let response: Response;
    try {
      response = await fetch("/student/chat/api", {
        method: "POST", credentials: "same-origin", cache: "no-store", signal,
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
    } catch {
      throw new ChatError("uncertain");
    }
    if (response.status === 401 || response.status === 403) throw new ChatError("session");
    if (!response.ok) throw new ChatError(response.status === 503 ? "unavailable" : "uncertain");
    try {
      return { response: parseAgentResponse(await response.json()) };
    } catch {
      throw new ChatError("invalid");
    }
  },
};

export function money(currency: "IDR" | "CNY", minor: number): string {
  if (!Number.isSafeInteger(minor) || minor < 0) throw new Error("Invalid money");
  const amount = BigInt(minor);
  const scale = currency === "CNY" ? BigInt(100) : BigInt(1);
  const major = new Intl.NumberFormat("en-US").format(amount / scale);
  const fraction = currency === "CNY" ? `.${String(amount % scale).padStart(2, "0")}` : "";
  return `${currency} ${major}${fraction}`;
}

export function dateTime(value: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
    timeZone: "Asia/Shanghai", hour12: false,
  }).format(new Date(value)) + " CST";
}

export function visibleText(value: string): string {
  return value
    .replace(/\bBearer\s+[^\s]+/gi, "[hidden credential]")
    .replace(/\b(?:sk-|ghp_)[A-Za-z0-9_-]+/g, "[hidden credential]")
    .replace(/\b(?:acct_|session_|tenant_|stu_|par_|benef_|approval_)[A-Za-z0-9_.:-]+/g, "[private reference]")
    .replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, "[hidden email]")
    .replace(/\b\d{10,}\b/g, "[hidden identifier]");
}
