import Link from "next/link";
import { StudentHeader } from "../../components/workspace-header";
import { dateTime, money } from "../chat/chat-types";
import {
  ActivityLog, HeldNotice, IntentSummary, QuoteBreakdown, ReceiptCard, SimulatedBanner, Stat, TrustTimeline,
  UntrustedDocuments,
} from "./components";
import { ExceptionActions } from "./exception-actions";
import { IntentActions } from "./intent-actions";
import { OwnerApproval } from "./owner-approval";
import { RouteChoices } from "./route-choices";
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
  return <main id="main-content" tabIndex={-1} lang={lang} className={styles.page}>
    <StudentHeader payments lang={lang} />
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
  const topup = item.state === "PARTIALLY_POSTED" && item.topup_permitted && item.shortfall_minor > 0;
  const revisable = pending?.state === "AWAITING_APPROVAL" || pending?.state === "AUTHORIZED";
  const ownPending = pending?.state === "AWAITING_APPROVAL" && pending.funded_by_requester;
  const mode = pending ? (revisable ? "revise" : null) : item.state === "UNPAID" ? "create" : topup ? "topup" : null;
  const [payment, quotes, options, transferTrail, intentTrail, approvals] = await Promise.all([
    transferId ? financeGet<Schema["PaymentResult"]>(`/api/v1/transfers/${transferId}`) : null,
    mode ? financeGet<Schema["FxQuote"][]>(`/api/v1/quotes?obligation_id=${item.id}`) : null,
    mode ? financeGet<Schema["PaymentOptions"]>(`/api/v1/tuition/obligations/${item.id}/payment-options`) : null,
    transferId ? financeGet<Schema["AuditEntry"][]>(`/api/v1/audit?resource_id=${transferId}`) : null,
    pending ? financeGet<Schema["AuditEntry"][]>(`/api/v1/audit?resource_id=${pending.id}`) : null,
    ownPending ? financeGet<Schema["ApprovalView"][]>("/api/v1/student/approvals") : null,
  ]);
  const ownerApproval = approvals?.ok && pending ? approvals.data.find(item =>
    item.intent_id === pending.id && item.terms_hash === pending.terms_hash && item.state === "PENDING") : undefined;
  const activity = [...(intentTrail?.ok ? intentTrail.data : []), ...(transferTrail?.ok ? transferTrail.data : [])]
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
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
      <h3>{ownPending ? (lang === "id" ? "Menunggu persetujuan Anda" : "Waiting for your approval") : paymentStateLabels[pending.state][lang]}</h3>
      <IntentSummary intent={pending} lang={lang} />
      {pending.state === "AWAITING_APPROVAL" && <p className={styles.notice}>{ownPending
        ? (lang === "id" ? "Anda pemilik dana. Tinjau dan setujui rincian sebelum melanjutkan." : "You own these funds. Review and approve the exact terms before continuing.") : ui.waitingOwner[lang]}</p>}
      {ownerApproval && <OwnerApproval approval={ownerApproval} lang={lang} />}
      {ownPending && !ownerApproval && <p className={styles.notice}>{lang === "id" ? "Persetujuan saat ini tidak tersedia. Muat ulang atau minta rincian persetujuan terbaru." : "A current reviewable approval is unavailable. Refresh or request current approval terms."}</p>}
      {pending.state === "ON_HOLD" && <p className={styles.notice} role="alert">
        {safeNextStep[pending.hold_reason ?? "SECURITY_HOLD"][lang]}
      </p>}
      <IntentActions lang={lang} intentId={pending.id} canContinue={pending.state === "AUTHORIZED"}
        payee={pending.beneficiary_label} total={money(pending.source_currency, pending.source_total_minor)}
        canRequestApproval={pending.state === "AWAITING_APPROVAL" && !ownerApproval} />
    </section>}
    {item.state !== "PAID" && item.state !== "UNPAID" && <p className={styles.notice}>{ui.noPay[lang]}</p>}
    {payment?.ok && <ReceiptCard payment={payment.data} lang={lang} />}
    {quotes?.ok && quotes.data.length > 0 && <QuoteBreakdown quotes={quotes.data} lang={lang} />}
    {mode && quotes?.ok && options?.ok && <RouteChoices key={pending?.id ?? item.id} lang={lang} mode={mode} obligationId={item.id}
      currentIntentId={pending?.id} currentQuoteId={pending?.quote_id}
      currentFundingOwnerSelf={pending?.funded_by_requester}
      options={options.data} quotes={quotes.data} />}
    {item.state === "PARTIALLY_POSTED" && !item.topup_permitted && <p className={styles.notice}>
      {ui.shortfallTitle[lang]}: {money(item.currency, item.shortfall_minor)}. {safeNextStep.TOPUP_NOT_PERMITTED[lang]}
    </p>}
    {caseState?.ok && <p>{caseStateLabels[caseState.data.state][lang]}</p>}
    {activity.length > 0 && <ActivityLog entries={activity} lang={lang} />}
    {payment && !payment.ok && payment.error && <HeldNotice error={payment.error} lang={lang} />}
    {item.state !== "PAID" && item.state !== "UNPAID" && <ExceptionActions
      lang={lang} obligationId={item.id} transferId={transferId} caseId={item.active_case_id ?? undefined}
      canOpenCase={item.state === "EXCEPTION" && delivered && !item.active_case_id}
      canSubmitCase={caseState?.ok === true && ["READY", "NEEDS_INFO"].includes(caseState.data.state)} />}
  </section>;
}
