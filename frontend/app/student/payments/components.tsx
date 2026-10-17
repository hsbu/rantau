import { dateTime, money } from "../chat/chat-types";
import type { Schema } from "./finance-api";
import styles from "./payments.module.css";
import { type Lang, safeNextStep, ui } from "./status-labels";
import type { TrustStep } from "./trust";

export function SimulatedBanner({ lang }: { lang: Lang }) {
  return <p className={styles.banner} role="note">{ui.simulated[lang]}</p>;
}

export function TrustTimeline({ steps, lang }: { steps: TrustStep[]; lang: Lang }) {
  return <ol className={styles.timeline} aria-label="trust states">
    {steps.map(step => <li key={step.key} className={`${styles.step} ${styles[step.status] ?? ""}`}>
      {step.label[lang]}
    </li>)}
  </ol>;
}

export function Stat({ label, value }: { label: string; value: string }) {
  return <div className={styles.stat}><span>{label}</span><strong>{value}</strong></div>;
}

export function QuoteBreakdown({ quotes, lang }: { quotes: Schema["FxQuote"][]; lang: Lang }) {
  return <table className={styles.table}>
    <caption>{ui.quotes[lang]}</caption>
    <thead><tr>
      <th>Route</th><th>{ui.principal[lang]}</th><th>{ui.fee[lang]}</th>
      <th>{ui.total[lang]}</th><th>{ui.recipient[lang]}</th><th>{ui.eta[lang]}</th>
    </tr></thead>
    <tbody>{quotes.map(quote => <tr key={quote.id}>
      <td>{quote.provider}</td>
      <td>{money(quote.source_currency, quote.source_principal_minor)}</td>
      <td>{money(quote.source_currency, quote.fee_minor)}</td>
      <td><strong>{money(quote.source_currency, quote.source_total_minor)}</strong></td>
      <td>{money(quote.destination_currency, quote.destination_amount_minor)}</td>
      <td>{dateTime(quote.estimated_delivery_at)}</td>
    </tr>)}</tbody>
  </table>;
}

export function ReceiptCard({ payment, lang }: { payment: Schema["PaymentResult"]; lang: Lang }) {
  return <div className={styles.grid}>
    <Stat label={ui.receipt[lang]} value={payment.receipt_reference ?? "-"} />
    <Stat label={ui.provider[lang]} value={payment.transfer_status} />
  </div>;
}

export function HeldNotice({ error, lang }: { error: Schema["DomainError"]; lang: Lang }) {
  return <p className={styles.notice} role="alert">{safeNextStep[error.reason_code][lang]}</p>;
}
