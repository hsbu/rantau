import type { Schema, ActionSummary } from "./chat-types";
import { visibleText } from "./chat-types";

type Snapshot = Schema["AgentDetailSnapshot"];
type Obj = Record<string, unknown>;
const tuitionStates = ["UNPAID", "AWAITING_POSTING", "PARTIALLY_POSTED", "PAID", "EXCEPTION", "RECONCILIATION_PENDING", "ESCALATED"];
const paymentStates = ["DRAFT", "AWAITING_APPROVAL", "AUTHORIZED", "ON_HOLD", "PROCESSING", "DELIVERED", "FAILED", "OUTCOME_UNKNOWN", "REJECTED", "EXPIRED", "CANCELLED"];
const approvalStates = ["REQUESTED", "PENDING", "APPROVED", "REJECTED", "EXPIRED", "REVOKED", "INVALIDATED_BY_CHANGE", "CONSUMED"];
const caseStates = ["OPEN", "EVIDENCE_REQUIRED", "READY", "SUBMITTED", "UNDER_REVIEW", "RESOLVED", "REJECTED", "NEEDS_INFO", "ESCALATED"];
function object(v: unknown, fields: string[]): v is Obj {
  return !!v && typeof v === "object" && !Array.isArray(v) && Object.keys(v).every(k => fields.includes(k));
}
function amount(v: unknown): v is number { return typeof v === "number" && Number.isSafeInteger(v) && v >= 0; }
function date(v: unknown): v is string {
  return typeof v === "string" && v.length <= 40 && /^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$/.test(v) && Number.isFinite(Date.parse(v));
}
function label(v: unknown): v is string {
  return typeof v === "string" && v.trim().length > 0 && v.length <= 120 && !/[<>]/.test(v)
    && !Array.from(v).some(c => c.charCodeAt(0) < 32) && visibleText(v) === v;
}
function member(v: unknown, values: string[]) { return typeof v === "string" && values.includes(v); }
function optional(v: unknown, predicate: (value: unknown) => boolean) { return v === undefined || v === null || predicate(v); }

// Validate every nested field before retaining any presentation data in browser memory.
export function parseDetailSnapshot(value: unknown, expectedRun: string): Snapshot {
  const fail = () => { throw new Error("Invalid detail snapshot"); };
  if (!object(value, ["run_id", "revision", "checked_at", "simulation_at", "summary"]) || value.run_id !== expectedRun
    || !amount(value.revision) || value.revision < 1 || !date(value.checked_at) || !date(value.simulation_at)) return fail();
  if (value.summary == null) return { run_id: expectedRun, revision: value.revision, checked_at: value.checked_at, simulation_at: value.simulation_at, summary: null };
  const s = value.summary;
  if (!object(s, ["obligation", "quote", "approval", "payment", "case", "intent_state", "beneficiary", "funding"])
    || !label(s.beneficiary) || !label(s.funding) || !optional(s.intent_state, v => member(v, paymentStates))) return fail();
  const o = s.obligation;
  if (!object(o, ["amount_due_minor", "posted_minor", "balance_minor", "due_at", "state", "posting_deadline_at", "shortfall_minor", "topup_permitted"])
    || !amount(o.amount_due_minor) || !o.amount_due_minor || !amount(o.posted_minor) || !amount(o.balance_minor)
    || o.posted_minor + o.balance_minor !== o.amount_due_minor || !date(o.due_at) || !member(o.state, tuitionStates)
    || (o.state === "PAID") !== (o.balance_minor === 0) || !optional(o.posting_deadline_at, date)
    || !amount(o.shortfall_minor) || typeof o.topup_permitted !== "boolean") return fail();
  if (s.quote != null) {
    const q = s.quote;
    if (!object(q, ["provider", "source_currency", "destination_currency", "source_principal_minor", "fee_minor", "source_total_minor", "destination_amount_minor", "rate", "expires_at", "estimated_delivery_at"])
      || !label(q.provider) || q.source_currency !== "IDR" || q.destination_currency !== "CNY"
      || !amount(q.source_principal_minor) || !q.source_principal_minor || !amount(q.fee_minor)
      || !amount(q.source_total_minor) || q.source_total_minor !== q.source_principal_minor + q.fee_minor
      || !amount(q.destination_amount_minor) || !q.destination_amount_minor
      || typeof q.rate !== "string" || q.rate.length > 40 || !/^(?:0|[1-9]\d{0,8})(?:\.\d{1,28})?$/.test(q.rate) || Number(q.rate) <= 0
      || !date(q.expires_at) || !date(q.estimated_delivery_at)) return fail();
  }
  if (s.approval != null) {
    const a = s.approval;
    if (!object(a, ["state", "expires_at", "owner"]) || !member(a.state, approvalStates) || !date(a.expires_at) || !member(a.owner, ["SELF", "OTHER"])) return fail();
  }
  if (s.payment != null && (!object(s.payment, ["transfer_status", "linked_posting"]) || !member(s.payment.transfer_status, paymentStates) || typeof s.payment.linked_posting !== "boolean")) return fail();
  if (s.case != null && (!object(s.case, ["state", "evidence_missing"]) || !member(s.case.state, caseStates) || !Array.isArray(s.case.evidence_missing) || s.case.evidence_missing.length > 10 || !s.case.evidence_missing.every(label))) return fail();
  return value as Snapshot;
}

export function actionSummary(snapshot: Snapshot): ActionSummary | undefined {
  const s = snapshot.summary;
  if (!s) return undefined;
  return { ...s, quote: s.quote ?? undefined, approval: s.approval ?? undefined, payment: s.payment ?? undefined,
    case: s.case ?? undefined, intent_state: s.intent_state ?? undefined, asOf: snapshot.simulation_at, checkedAt: snapshot.checked_at };
}
