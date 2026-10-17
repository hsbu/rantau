import type { Schema } from "./finance-api";
import { type Label, ui } from "./status-labels";

export type StepStatus = "done" | "current" | "todo" | "problem";
export type TrustStep = { key: string; label: Label; status: StepStatus };

// Presentation only: the backend decides every state; this maps it to a visible step.
export function trustSteps(
  detail: Schema["TuitionObligationDetail"],
  pending?: Schema["PaymentIntentView"],
): TrustStep[] {
  const transfer = detail.provider_status?.transfer_status;
  const paid = detail.state === "PAID";
  const sent = transfer !== undefined;
  const provider: StepStatus = transfer === "DELIVERED" ? "done"
    : transfer === "FAILED" || transfer === "OUTCOME_UNKNOWN" ? "problem"
    : transfer === "PROCESSING" ? "current" : "todo";
  const posting: StepStatus = paid || detail.posted_minor > 0 ? "done"
    : detail.state === "AWAITING_POSTING" ? "current" : "todo";
  const reconciliation: StepStatus = paid && detail.reconciliation_resolved ? "done"
    : detail.state === "RECONCILIATION_PENDING" ? "current"
    : detail.state === "EXCEPTION" || detail.state === "ESCALATED" ? "problem" : "todo";
  return [
    { key: "sponsor", label: ui.steps.sponsor, status: sent ? "done" : sponsorStatus(pending) },
    { key: "provider", label: ui.steps.provider, status: provider },
    { key: "posting", label: ui.steps.posting, status: posting },
    { key: "reconciliation", label: ui.steps.reconciliation, status: reconciliation },
    { key: "paid", label: ui.steps.paid, status: paid ? "done" : "todo" },
  ];
}

function sponsorStatus(pending?: Schema["PaymentIntentView"]): StepStatus {
  if (!pending) return "todo";
  if (pending.state === "AWAITING_APPROVAL") return "current";
  return pending.state === "ON_HOLD" ? "problem" : "done";
}
