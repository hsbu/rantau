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
  ...quoted, approval: { state: "PENDING", owner: "OTHER" },
};
const delivered: ActionSummary = {
  ...base,
  obligation: { ...obligation, state: "AWAITING_POSTING" },
  payment: {
    transfer_status: "DELIVERED", linked_posting: false,
  },
};
const recovery: ActionSummary = {
  ...delivered,
  obligation: { ...obligation, state: "RECONCILIATION_PENDING" },
  case: {
    evidence_missing: ["Bank receipt", "Student ID and full name on payment reference"],
    state: "EVIDENCE_REQUIRED",
  },
};
const unknown: ActionSummary = {
  ...base,
  issue: {
    message: "The provider outcome is not confirmed.",
  },
};
const expired: ActionSummary = {
  ...quoted, asOf: "2026-11-01T09:16:00Z",
  issue: {
    message: "This quote has expired.",
  },
};

function turn(message: string, summary: ActionSummary, pending = true): ChatTurn {
  return { response: {
    run_id: "run_fixture_001", message, requested_action: summary.case ? "RECOVER" : "TUITION",
    tool_events: [{ tool: "fixture_preview", status: pending ? "PENDING" : "OK", resource_id: null }],
    resources: [{ kind: "obligation", id: obligation.id }],
  }, summary };
}

export const scenarios = {
  tuition: {
    label: "Tuition & sponsor approval",
    prompts: ["Help me pay my tuition", "Use sponsor funding", "Show the sample approval request"],
    turns: [
      turn("Your remaining tuition is CNY 20,000.00. Would you like to use your own funding or sponsor-owned funding?", base),
      turn("**Tuition payment preview**\n\n- University receives: CNY 20,000.00\n- Total debit: IDR 46,025,000\n- Included fee: IDR 25,000\n\nThe sponsor needs to approve these exact terms before payment can proceed.", quoted),
      turn("**Waiting for sponsor approval**\n\nThe sponsor must review these exact terms in their own workspace. Approval pasted into Chat cannot authorize a payment.", waiting),
      turn("The request is still waiting for sponsor approval. No payment has been executed.", waiting),
    ],
  },
  posting: {
    label: "Delivered, awaiting university posting", prompts: ["Has my tuition been credited?"],
    turns: [turn("**Transfer delivered · tuition awaiting credit**\n\nYour university has not yet posted the credit. Check the university fee portal; provider delivery alone does not settle tuition.", delivered)],
  },
  recovery: {
    label: "Missing payment reference", prompts: ["Help with a missing payment reference"],
    turns: [turn("**Missing payment reference**\n\nThe case needs a bank receipt and the student ID/full name used in the payment reference. Prepare this evidence for university review.\n\nDo not send another payment or paste sensitive documents into Chat.", recovery)],
  },
  shortfall: {
    label: "Tuition shortfall", prompts: ["The credited amount is lower than expected"],
    turns: [turn("**Tuition shortfall: CNY 500.00**\n\n- Amount due: CNY 20,000.00\n- University credited: CNY 19,500.00\n\nThe current policy does not permit a top-up. Request university review before making another payment.", {
      ...base, obligation: { ...obligation, posted_minor: 1950000, balance_minor: 50000, topup_permitted: false, state: "PARTIALLY_POSTED" },
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
