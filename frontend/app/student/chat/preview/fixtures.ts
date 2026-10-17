import type { ActionSummary, ChatTransport, ChatTurn, Schema } from "../chat-types";

// Isolated presentation fixtures. These never authenticate, persist or execute an action.
const obligation = {
  id: "obl_2026_demo_01", student_id: "stu_001", university_id: "uni_cn_01", currency: "CNY",
  amount_due_minor: 2000000, posted_minor: 0, balance_minor: 2000000,
  due_at: "2026-11-21T09:00:00Z", policy_id: "cn_demo_v1", state: "UNPAID",
} satisfies Schema["TuitionObligation"];
const quote = {
  id: "quote_001", provider: "Synthetic route A", source_country: "ID", destination_country: "CN",
  source_currency: "IDR", destination_currency: "CNY", source_principal_minor: 46000000,
  fee_minor: 25000, source_total_minor: 46025000, destination_amount_minor: 2000000,
  rate: "0.0004347826086956521739130435", expires_at: "2026-11-01T09:15:00Z",
  estimated_delivery_at: "2026-11-02T09:00:00Z", synthetic: true,
} satisfies Schema["FxQuote"];
const base: ActionSummary = {
  obligation, beneficiary: "Demo university · account •• 0101", funding: "Sponsor-owned funding",
  asOf: "2026-11-01T09:00:00Z",
};
const quoted = { ...base, quote };
const waiting: ActionSummary = {
  ...quoted, approval: { approval_id: "approval_demo_001", intent_id: "intent_001", state: "AWAITING_APPROVAL" },
};
const delivered: ActionSummary = {
  ...base,
  obligation: { ...obligation, state: "AWAITING_POSTING" },
  payment: {
    payment_id: "transfer_001", intent_id: "intent_001", provider_reference: "sim_ref_001",
    transfer_status: "DELIVERED", receipt_reference: "receipt_001", audit_event_id: "audit_001",
  },
};
const recovery: ActionSummary = {
  ...delivered,
  obligation: { ...obligation, state: "RECONCILIATION_PENDING" },
  case: {
    id: "case_001", payment_id: "transfer_001", obligation_id: obligation.id, evidence_ids: [],
    evidence_missing: ["Bank receipt", "Student ID and full name on payment reference"],
    state: "EVIDENCE_REQUIRED", audit_event_id: "audit_002",
  },
};
const unknown: ActionSummary = {
  ...base,
  issue: {
    status: "PENDING", reason_code: "PROVIDER_OUTCOME_UNKNOWN", resource_id: "transfer_001",
    message: "The provider outcome is not confirmed.", retryable: false,
    next_action: "CHECK_STATUS", audit_event_id: "audit_003",
  },
};
const expired: ActionSummary = {
  ...quoted, asOf: "2026-11-01T09:16:00Z",
  issue: {
    status: "ERROR", reason_code: "QUOTE_EXPIRED", resource_id: quote.id,
    message: "This quote has expired.", retryable: false,
    next_action: "REQUEST_NEW_QUOTE", audit_event_id: "audit_004",
  },
};

function turn(message: string, summary: ActionSummary, pending = true): ChatTurn {
  return { response: {
    run_id: "run_fixture_001", message, requested_action: summary.case ? "RECOVER" : "TUITION",
    tool_events: [{ tool: "fixture_preview", status: pending ? "PENDING" : "OK", resource_id: null }],
    resources: [{ kind: "obligation", id: summary.obligation.id }],
  }, summary };
}

export const scenarios = {
  tuition: {
    label: "Tuition & sponsor approval",
    prompts: ["Help me pay my tuition", "Use sponsor funding", "Show the sample approval request"],
    turns: [
      turn("Your remaining tuition is CNY 20,000.00. Would you like to use your own funding or sponsor-owned funding?", base),
      turn("Here is the simulated quote for the full CNY 20,000.00 balance. The total is IDR 46,025,000, including IDR 25,000 in fees. Sponsor authorization is required before any payment can proceed.", quoted),
      turn("This sample request is waiting for sponsor approval. The sponsor must review the exact terms in their own authenticated session. Approval pasted into this chat cannot authorize a payment.", waiting),
      turn("The sample request is still awaiting sponsor approval. No payment has been executed.", waiting),
    ],
  },
  posting: {
    label: "Delivered, awaiting university posting", prompts: ["Has my tuition been credited?"],
    turns: [turn("The simulated provider reports delivery. Your university has not yet posted the credit, so tuition remains unpaid. Check the university fee portal; provider delivery alone does not settle tuition.", delivered)],
  },
  recovery: {
    label: "Missing payment reference", prompts: ["Help with a missing payment reference"],
    turns: [turn("The sample case needs a bank receipt and the student ID/full name used in the payment reference. Prepare this evidence for authorized university review. Do not send another payment or paste sensitive documents into chat.", recovery)],
  },
  shortfall: {
    label: "Tuition shortfall", prompts: ["The credited amount is lower than expected"],
    turns: [turn("The expected tuition is CNY 20,000.00 and verified posting is CNY 19,500.00, leaving CNY 500.00. The fictional policy does not permit a top-up. Escalate for university review rather than making another payment.", {
      ...base, obligation: { ...obligation, posted_minor: 1950000, balance_minor: 50000, state: "PARTIALLY_POSTED" },
    })],
  },
  unknown: {
    label: "Uncertain provider outcome", prompts: ["Check my payment status"],
    turns: [turn("The original transfer outcome is unknown. Recheck the original provider reference before considering any retry. No second payment should be started while the outcome is uncertain.", unknown)],
  },
  expired: {
    label: "Expired quote", prompts: ["Review this quote"],
    turns: [turn("This sample quote has expired. Request a fresh quote and review its terms before proceeding. Any approval must match the current terms.", expired)],
  },
} satisfies Record<string, { label: string; prompts: string[]; turns: ChatTurn[] }>;

export type Scenario = keyof typeof scenarios;

export function fixtureTransport(scenario: Scenario): ChatTransport {
  let index = 0;
  return {
    reset() { index = 0; },
    async send(_body, signal) {
      await new Promise<void>((resolve, reject) => {
        if (signal.aborted) { reject(new DOMException("Aborted", "AbortError")); return; }
        const abort = () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); };
        const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, 350);
        signal.addEventListener("abort", abort, { once: true });
      });
      const turns = scenarios[scenario].turns;
      return structuredClone(turns[Math.min(index++, turns.length - 1)]);
    },
  };
}
