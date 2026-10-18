import Link from "next/link";
import { dateTime, money } from "../chat/chat-types";
import {
  HeldNotice, IntentSummary, QuoteBreakdown, ReceiptCard, SimulatedBanner, Stat, TrustTimeline,
  UntrustedDocuments,
} from "./components";
import { ExceptionActions } from "./exception-actions";
import { IntentActions } from "./intent-actions";
import { type Schema, financeGet } from "./finance-api";
import styles from "./payments.module.css";
import { caseStateLabels, paymentStateLabels, pickLang, safeNextStep, tuitionStateLabels, ui } from "./status-labels";
import { trustSteps } from "./trust";

export const metadata = { title: "Payments | Rantau" };
export const dynamic = "force-dynamic";

type Props = { searchParams: Promise<{ lang?: string }> };
const PENDING: Schema["PaymentState"][] = ["AWAITING_APPROVAL", "AUTHORIZED", "ON_HOLD"];

export default async function StudentPayments({ searchParams }: Props) {
  const lang = pickLang((await searchParams).lang);
  const [list, intents, documents] = await Promise.all([
    financeGet<Schema["TuitionObligationDetail"][]>("/api/v1/tuition/obligations"),
    financeGet<Schema["PaymentIntentView"][]>("/api/v1/payment-intents"),
    financeGet<Schema["UntrustedDocument"][]>("/api/v1/documents"),
  ]);
  const pending = intents.ok ? intents.data.filter(item => PENDING.includes(item.state)) : [];
  return <main className={styles.page}>
    <SimulatedBanner lang={lang} />
    <h1>{ui.title[lang]}</h1>
    <p className={styles.lang}>
      <Link href="?lang=en">English</Link> · <Link href="?lang=id">Bahasa Indonesia</Link>
    </p>
    {!list.ok && <p className={styles.notice} role="alert">
      {list.reason === "signin" ? ui.signIn[lang] : ui.unavailable[lang]}
      {list.reason === "signin" && <> <Link href="/student/sign-in?next=payments">{lang === "id" ? "Masuk sebagai mahasiswa →" : "Student sign-in →"}</Link></>}
    </p>}
    {list.ok && list.data.length === 0 && <p>{ui.none[lang]}</p>}
    {list.ok && await Promise.all(list.data.map(item => <ObligationCard key={item.id} item={item} lang={lang}
      pending={pending.find(intent => intent.obligation_id === item.id)} />))}
    {documents.ok && documents.data.length > 0 && <UntrustedDocuments documents={documents.data} lang={lang} />}
  </main>;
}

async function ObligationCard(
  { item, lang, pending }: { item: Schema["TuitionObligationDetail"]; lang: "en" | "id"; pending?: Schema["PaymentIntentView"] },
) {
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
    <TrustTimeline steps={trustSteps(item, pending)} lang={lang} />
    {pending && <section aria-label="pending payment">
      <h3>{paymentStateLabels[pending.state][lang]}</h3>
      <IntentSummary intent={pending} lang={lang} />
      {pending.state === "AWAITING_APPROVAL" && <p className={styles.notice}>{ui.waitingOwner[lang]}</p>}
      {pending.state === "ON_HOLD" && <p className={styles.notice} role="alert">{safeNextStep.SECURITY_HOLD[lang]}</p>}
      <IntentActions lang={lang} intentId={pending.id} canContinue={pending.state === "AUTHORIZED"} />
    </section>}
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
