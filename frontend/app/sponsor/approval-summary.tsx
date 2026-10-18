import type { components } from "../../lib/api-contracts/generated";
import { money } from "../student/chat/chat-types";
import styles from "./sponsor.module.css";

export type SummaryLanguage = "en" | "id";
type Approval = components["schemas"]["ApprovalView"];
const labels = {
  en: ["From", "Amount", "Fee", "Total debit", "Recipient receives"],
  id: ["Sumber dana", "Jumlah", "Biaya", "Total pendebitan", "Dana yang diterima"],
};

/** Translate presentation only; immutable terms and authority come from the same view. */
export function ApprovalSummary({ item, language }: { item: Approval; language: SummaryLanguage }) {
  const text = labels[language];
  return <div lang={language}>
    <dl className={styles.amounts}>
      <div><dt>{text[0]}</dt><dd>{item.source_label}</dd></div>
      <div><dt>{text[1]}</dt><dd>{money(item.source_currency, item.source_principal_minor)}</dd></div>
      <div><dt>{text[2]}</dt><dd>{money(item.source_currency, item.fee_minor)}</dd></div>
      <div className={styles.total}><dt>{text[3]}</dt><dd>{money(item.source_currency, item.source_total_minor)}</dd></div>
      <div className={styles.destination}><dt>{text[4]}</dt><dd>{money(item.destination_currency, item.destination_amount_minor)}</dd></div>
    </dl>
    <p className={styles.muted}>{language === "id"
      ? "Persetujuan mengizinkan upaya pembayaran sesuai rincian ini. Persetujuan tidak memindahkan dana atau membuktikan uang kuliah telah tercatat."
      : "Approval permits an attempt using these exact terms. It does not move funds or prove tuition has been posted."}</p>
  </div>;
}
