import Link from "next/link";
import { dateTime, money } from "../chat/chat-types";
import { HeldNotice, QuoteBreakdown, ReceiptCard, SimulatedBanner, Stat, TrustTimeline } from "./components";
import { ExceptionActions } from "./exception-actions";
import { type Schema, financeGet } from "./finance-api";
import styles from "./payments.module.css";
import { caseStateLabels, pickLang, tuitionStateLabels, ui } from "./status-labels";
import { trustSteps } from "./trust";

export const metadata = { title: "Payments | Rantau" };
export const dynamic = "force-dynamic";

type Props = { searchParams: Promise<{ lang?: string }> };

export default async function StudentPayments({ searchParams }: Props) {
  const lang = pickLang((await searchParams).lang);
  const list = await financeGet<Schema["TuitionObligationDetail"][]>("/api/v1/tuition/obligations");
  return <main className={styles.page}>
    <SimulatedBanner lang={lang} />
    <h1>{ui.title[lang]}</h1>
    <p className={styles.lang}>
      <Link href="?lang=en">English</Link> · <Link href="?lang=id">Bahasa Indonesia</Link>
    </p>
    {!list.ok && <p className={styles.notice} role="alert">
      {list.reason === "signin" ? ui.signIn[lang] : ui.unavailable[lang]}
    </p>}
    {list.ok && list.data.length === 0 && <p>{ui.none[lang]}</p>}
    {list.ok && await Promise.all(list.data.map(item => <ObligationCard key={item.id} item={item} lang={lang} />))}
  </main>;
}

async function ObligationCard({ item, lang }: { item: Schema["TuitionObligationDetail"]; lang: "en" | "id" }) {
  const transferId = item.provider_status?.payment_id;
  const [payment, quotes] = await Promise.all([
    transferId ? financeGet<Schema["PaymentResult"]>(`/api/v1/transfers/${transferId}`) : null,
    item.state === "UNPAID" ? financeGet<Schema["FxQuote"][]>(`/api/v1/quotes?obligation_id=${item.id}`) : null,
  ]);
  const delivered = item.provider_status?.transfer_status === "DELIVERED";
  const caseState = item.active_case_id
    ? await financeGet<Schema["ReconciliationCase"]>(`/api/v1/reconciliations/${item.active_case_id}`) : null;
  return <section className={styles.card} aria-label={item.id}>
    <h2>{tuitionStateLabels[item.state][lang]}</h2>
    <div className={styles.grid}>
      <Stat label={ui.due[lang]} value={money(item.currency, item.amount_due_minor)} />
      <Stat label={ui.posted[lang]} value={money(item.currency, item.posted_minor)} />
      <Stat label={ui.remaining[lang]} value={money(item.currency, item.balance_minor)} />
      {item.posting_deadline_at && <Stat label={ui.deadline[lang]} value={dateTime(item.posting_deadline_at)} />}
    </div>
    <TrustTimeline steps={trustSteps(item)} lang={lang} />
    {item.state !== "PAID" && item.state !== "UNPAID" && <p className={styles.notice}>{ui.noPay[lang]}</p>}
    {payment?.ok && <ReceiptCard payment={payment.data} lang={lang} />}
    {quotes?.ok && quotes.data.length > 0 && <QuoteBreakdown quotes={quotes.data} lang={lang} />}
    {caseState?.ok && <p>{caseStateLabels[caseState.data.state][lang]}</p>}
    {payment && !payment.ok && payment.error && <HeldNotice error={payment.error} lang={lang} />}
    {item.state !== "PAID" && item.state !== "UNPAID" && <ExceptionActions
      lang={lang} obligationId={item.id} transferId={transferId} caseId={item.active_case_id ?? undefined}
      canOpenCase={item.state === "EXCEPTION" && delivered && !item.active_case_id}
      canSubmitCase={caseState?.ok === true && ["READY", "NEEDS_INFO"].includes(caseState.data.state)} />}
  </section>;
}
