import type { ActionSummary } from "./chat-types";
import { dateTime, money, visibleText } from "./chat-types";
import styles from "./chat.module.css";

export function ActionPanel({ summary, preview, unavailable = false }: { summary?: ActionSummary; preview: boolean; unavailable?: boolean }) {
  const quote = summary?.quote;
  const expired = !!quote && new Date(quote.expires_at) <= new Date(summary.checkedAt ?? summary.asOf);
  return <aside className={styles.summary} aria-labelledby="summary-title">
    <div className={styles.summaryHeading}><span className={styles.kicker}>THE DETAILS</span>
      <h2 id="summary-title">Your next step,{" "}<br />made clear.</h2>
    </div>
    {unavailable && <section className={styles.notice} role="status" aria-label="Details unavailable">
      <div><h3>Details unavailable</h3><p>Your chat response is available, but current payment details could not be verified. Check Payments before repeating a financial request.</p></div>
    </section>}
    {!summary ? <div className={styles.emptySummary}>
      <span className={styles.summaryGlyph} aria-hidden="true">↗</span>
      <h3>A little clarity goes a long way.</h3>
      <p>Start a conversation to review your tuition, understand a quote or find the next step for a payment.</p>
      <p className={styles.muted}>Your payment details will appear here when they’re ready for review.</p>
    </div> : <>
      <section className={styles.balance} aria-label="Tuition balance">
        <span>Remaining tuition</span>
        <strong>{money("CNY", summary.obligation.balance_minor)}</strong>
        <dl className={styles.rows}>
          <div><dt>Expected</dt><dd>{money("CNY", summary.obligation.amount_due_minor)}</dd></div>
          <div><dt>University posted</dt><dd>{money("CNY", summary.obligation.posted_minor)}</dd></div>
        </dl>
        <p className={styles.small}>University record: {tuitionLabel(summary.obligation.state)}</p>
      </section>
      {summary.intent_state && <section className={styles.notice} aria-label="Request status">
        <div><h3>Request: {paymentLabel(summary.intent_state)}</h3><p>{summary.intent_state === "ON_HOLD"
          ? "This request is blocked pending separate trusted security review. Chat cannot clear the hold."
          : "This is the saved request state. Use Payments to review it; displaying this card requests no execution."}</p></div>
      </section>}
      <section className={styles.detailBlock} aria-label="Action summary">
        <h3>Tuition payment</h3>
        <dl className={styles.rows}>
          <div><dt>Recipient</dt><dd>{visibleText(summary.beneficiary)}</dd></div>
          <div><dt>Funding</dt><dd>{visibleText(summary.funding)}</dd></div>
          <div><dt>Tuition due</dt><dd>{dateTime(summary.obligation.due_at)}</dd></div>
          {summary.obligation.posting_deadline_at && <div><dt>Posting deadline</dt><dd>{dateTime(summary.obligation.posting_deadline_at)}</dd></div>}
        </dl>
      </section>
      {quote && <section className={styles.detailBlock} aria-label="Quote breakdown">
        <div className={styles.inlineHeading}><h3>Quote breakdown</h3><span className={expired ? styles.warningTag : styles.tag}>{expired ? "Expired" : preview ? "Sample" : "Quote"}</span></div>
        <p className={styles.small}>{visibleText(quote.provider)} · IDR → CNY</p>
        <dl className={styles.rows}>
          <div><dt>Transfer amount</dt><dd>{money(quote.source_currency, quote.source_principal_minor)}</dd></div>
          <div><dt>Transfer fee</dt><dd>{money(quote.source_currency, quote.fee_minor)}</dd></div>
          <div className={styles.total}><dt>Total debit</dt><dd>{money(quote.source_currency, quote.source_total_minor)}</dd></div>
          <div><dt>Expected delivery</dt><dd>{money(quote.destination_currency, quote.destination_amount_minor)}</dd></div>
          <div><dt>Rate (CNY per IDR)</dt><dd className={styles.rate}>{quote.rate}</dd></div>
          <div><dt>Quote expires</dt><dd>{dateTime(quote.expires_at)}</dd></div>
          <div><dt>Provider estimate</dt><dd>{dateTime(quote.estimated_delivery_at)}</dd></div>
        </dl>
        <p className={styles.small}>Provider delivery is separate from university posting.</p>
      </section>}
      {summary.approval && <section className={styles.notice} aria-label="Approval status">
        <span className={styles.statusMark} aria-hidden="true">◷</span>
        <div><h3>{approvalLabel(summary.approval)}</h3><p>{approvalExplanation(summary.approval)}</p>
          {summary.approval.expires_at && <p className={styles.small}>Approval expiry: {dateTime(summary.approval.expires_at)}</p>}
        </div>
      </section>}
      {summary.payment && <section className={styles.notice} aria-label="Payment status">
        <div><h3>Provider: {paymentLabel(summary.payment.transfer_status)}</h3>
          <p>University: {tuitionLabel(summary.obligation.state)}. {summary.obligation.state === "PAID"
            ? summary.payment.linked_posting ? "Verified university posting is linked to this payment." : "The obligation is credited, but posting for this particular payment is unverified."
            : "Tuition is complete only after verified posting covers the balance."}</p>
          {summary.payment.transfer_status === "OUTCOME_UNKNOWN" && <p>Check the original payment before any retry. Do not start a second payment.</p>}
        </div>
      </section>}
      {summary.case && <section className={styles.detailBlock} aria-label="Recovery steps">
        <h3>Recovery review</h3><p className={styles.small}>Case: {summary.case.state.replaceAll("_", " ").toLowerCase()}</p>
        {summary.case.evidence_missing.length > 0 ? <><h4>Evidence needed</h4><ol className={styles.steps}>{summary.case.evidence_missing.map(item => <li key={item}>{visibleText(item)}</li>)}</ol></>
          : <p className={styles.small}>No missing evidence is currently reported. Case submission alone does not prove university posting.</p>}
        <p className={styles.small}>Use Payments for authorized evidence review. Keep private documents out of chat.</p>
      </section>}
      {summary.issue && <section className={styles.notice} aria-label="Safe next step">
        <div><h3>{expired ? "Get a fresh quote" : "Check the original transfer"}</h3><p>{visibleText(summary.issue.message)} {expired ? "Review new terms before proceeding." : "Check status before retrying. Do not start a second payment."}</p></div>
      </section>}
      {summary.obligation.state === "PARTIALLY_POSTED" && <section className={styles.notice}>
        <div><h3>University review needed</h3><p>{summary.obligation.topup_permitted
          ? "The current policy permits separate top-up planning. Any additional payment requires its own current authorization in Payments."
          : summary.obligation.topup_permitted === false
            ? "The current policy does not permit a top-up. Escalate the shortfall for review."
            : "Top-up permission is unverified. Seek university review before any additional payment."}</p></div>
      </section>}
      {preview && <p className={styles.fixtureClock}>Fictional scenario time: {dateTime(summary.asOf)}. These are sample records, not a live quote or account.</p>}
      {!preview && <p className={styles.fixtureClock}>Records as of {dateTime(summary.asOf)}.{summary.checkedAt && <> Checked {dateTime(summary.checkedAt)}.</>} Current checks still apply before any payment.</p>}
    </>}
    <div className={styles.trustNote}><span aria-hidden="true">↳</span><p>You stay in control. Financial actions require server authorization; chat text cannot grant approval.</p></div>
  </aside>;
}

function approvalLabel(approval: NonNullable<ActionSummary["approval"]>) {
  if (["REQUESTED", "PENDING"].includes(approval.state)) return approval.owner === "SELF" ? "Waiting for your approval" : "Waiting for sponsor";
  const labels = { APPROVED: "Approval recorded", REJECTED: "Approval rejected", EXPIRED: "Approval expired", REVOKED: "Approval revoked", INVALIDATED_BY_CHANGE: "Terms changed", CONSUMED: "Approval already used", NOT_REQUIRED: "Separate owner approval not required" };
  return labels[approval.state as keyof typeof labels];
}

function approvalExplanation(approval: NonNullable<ActionSummary["approval"]>) {
  if (["REQUESTED", "PENDING"].includes(approval.state)) return "The funding owner must approve these exact terms in their own authenticated session. This pending request does not authorize execution.";
  if (approval.state === "APPROVED") return "Approval matches the saved request at this snapshot. Execution still rechecks current authority, quote expiry, holds and limits.";
  if (approval.state === "CONSUMED") return "This approval has already been used. Check the original payment; do not create a replacement request.";
  if (approval.state === "NOT_REQUIRED") return "The protected backend still checks current permission and all payment rules before execution.";
  return "This approval cannot authorize execution. Review the current request in Payments before continuing.";
}

function paymentLabel(state: NonNullable<ActionSummary["payment"]>["transfer_status"]) {
  const labels = { DRAFT: "Draft", AWAITING_APPROVAL: "Awaiting approval", AUTHORIZED: "Authorized", ON_HOLD: "On hold", PROCESSING: "Processing", DELIVERED: "Delivered", FAILED: "Failed", OUTCOME_UNKNOWN: "Outcome unknown", REJECTED: "Rejected", EXPIRED: "Expired", CANCELLED: "Cancelled" };
  return labels[state];
}

function tuitionLabel(state: ActionSummary["obligation"]["state"]) {
  const labels = {
    UNPAID: "Unpaid", AWAITING_POSTING: "Awaiting posting", PARTIALLY_POSTED: "Partially posted",
    PAID: "Paid", EXCEPTION: "Exception under review", RECONCILIATION_PENDING: "Reconciliation pending", ESCALATED: "Escalated",
  };
  return labels[state];
}
