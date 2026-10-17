import type { ActionSummary } from "./chat-types";
import { dateTime, money } from "./chat-types";
import styles from "./chat.module.css";

export function ActionPanel({ summary, preview }: { summary?: ActionSummary; preview: boolean }) {
  const quote = summary?.quote;
  const expired = !!quote && new Date(quote.expires_at) <= new Date(summary.asOf);
  return <aside className={styles.summary} aria-labelledby="summary-title">
    <div className={styles.summaryHeading}><span className={styles.kicker}>THE DETAILS</span>
      <h2 id="summary-title">Your next step,{" "}<br />made clear.</h2>
    </div>
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
      <section className={styles.detailBlock} aria-label="Action summary">
        <h3>Tuition payment</h3>
        <dl className={styles.rows}>
          <div><dt>Recipient</dt><dd>{summary.beneficiary}</dd></div>
          <div><dt>Funding</dt><dd>{summary.funding}</dd></div>
          <div><dt>Tuition due</dt><dd>{dateTime(summary.obligation.due_at)}</dd></div>
        </dl>
      </section>
      {quote && <section className={styles.detailBlock} aria-label="Quote breakdown">
        <div className={styles.inlineHeading}><h3>Quote breakdown</h3><span className={expired ? styles.warningTag : styles.tag}>{expired ? "Expired" : "Simulated"}</span></div>
        <p className={styles.small}>{quote.provider} · IDR → CNY</p>
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
        <div><h3>Waiting for sponsor</h3><p>The funding owner must approve these exact terms in their own authenticated session. No payment has been executed.</p></div>
      </section>}
      {summary.payment && <section className={styles.notice} aria-label="Payment status">
        <div><h3>Provider: {summary.payment.transfer_status === "DELIVERED" ? "Delivered" : "Pending verification"}</h3>
          <p>University: {tuitionLabel(summary.obligation.state)}. Tuition is complete only after verified posting covers the balance.</p></div>
      </section>}
      {summary.case && <section className={styles.detailBlock} aria-label="Recovery steps">
        <h3>Evidence needed</h3><p className={styles.small}>Case: {summary.case.state.replaceAll("_", " ").toLowerCase()}</p>
        <ol className={styles.steps}>{summary.case.evidence_missing.map(item => <li key={item}>{item}</li>)}</ol>
        <p className={styles.small}>Prepare evidence for authorized review. Keep private documents out of chat.</p>
      </section>}
      {summary.issue && <section className={styles.notice} aria-label="Safe next step">
        <div><h3>{expired ? "Get a fresh quote" : "Check the original transfer"}</h3><p>{summary.issue.message} {expired ? "Review new terms before proceeding." : "Check status before retrying. Do not start a second payment."}</p></div>
      </section>}
      {summary.obligation.state === "PARTIALLY_POSTED" && <section className={styles.notice}>
        <div><h3>University review needed</h3><p>The fictional policy does not permit a top-up. Escalate the shortfall for review.</p></div>
      </section>}
      {preview && <p className={styles.fixtureClock}>Fictional scenario time: {dateTime(summary.asOf)}. These are sample records, not a live quote or account.</p>}
    </>}
    <div className={styles.trustNote}><span aria-hidden="true">↳</span><p>You stay in control. Financial actions require server authorization; chat text cannot grant approval.</p></div>
  </aside>;
}

function tuitionLabel(state: ActionSummary["obligation"]["state"]) {
  const labels = {
    UNPAID: "Unpaid", AWAITING_POSTING: "Awaiting posting", PARTIALLY_POSTED: "Partially posted",
    PAID: "Paid", EXCEPTION: "Exception under review", RECONCILIATION_PENDING: "Reconciliation pending", ESCALATED: "Escalated",
  };
  return labels[state];
}
