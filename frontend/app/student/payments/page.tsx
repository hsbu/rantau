import Link from "next/link";
import { PageHeading, PageLanguage, WorkspaceState } from "../../components/workspace-page";
import pageStyles from "../../components/workspace-page.module.css";
import uiStyles from "../../components/ui.module.css";
import { StudentHeader } from "../../components/workspace-header";
import { dateTime, money } from "../chat/chat-types";
import {
  ActivityLog, HeldNotice, IntentSummary, QuoteBreakdown, ReceiptCard, SimulatedBanner, Stat, TrustTimeline,
  UntrustedDocuments,
} from "./components";
import { ExceptionActions } from "./exception-actions";
import { IntentActions } from "./intent-actions";
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
  return <><StudentHeader payments lang={lang} /><main id="main-content" tabIndex={-1} lang={lang} className={styles.page}>
    <PageHeading eyebrow={lang === "id" ? "Ruang mahasiswa" : "Student workspace"} title={ui.title[lang]}
      description={lang === "id" ? "Tinjau tagihan, ikuti pembayaran, dan periksa pencatatan universitas." : "Review what’s due, follow your payments and check university posting."}>
      <PageLanguage lang={lang} />
    </PageHeading>
    <SimulatedBanner lang={lang} />
    {!list.ok && <WorkspaceState label="Payment access" title={lang === "id"
      ? list.reason === "signin" ? "Pembayaran Anda, dalam satu tempat." : "Rincian pembayaran belum tersedia."
      : list.reason === "signin" ? "Your payments, in one place." : "Payment details are unavailable."}>
      <p role={list.reason === "signin" ? undefined : "alert"}>{list.reason === "signin" ? ui.signIn[lang] : ui.unavailable[lang]}</p>
      {list.reason === "signin" && <p>{lang === "id" ? "Gunakan akun mahasiswa untuk meninjau tagihan dan permintaan pembayaran Anda dengan aman." : "Use your student account to securely review your tuition and payment requests."}</p>}
      <div className={pageStyles.stateActions}>
        <Link className={uiStyles.button} href={list.reason === "signin" ? "/student/sign-in?next=payments" : `?lang=${lang}`}>
          {list.reason === "signin" ? lang === "id" ? "Masuk sebagai mahasiswa →" : "Student sign-in →" : lang === "id" ? "Perbarui status" : "Refresh status"}
        </Link>
        <Link className={`${uiStyles.button} ${uiStyles.secondary}`} href="/student/chat">{lang === "id" ? "Buka Chat" : "Open Chat"}</Link>
      </div>
    </WorkspaceState>}
    {list.ok && list.data.length === 0 && <WorkspaceState label="Payment access" title={lang === "id" ? "Belum ada tagihan untuk ditinjau." : "No tuition to review yet."}>
      <p>{ui.none[lang]}</p><p>{lang === "id" ? "Periksa kembali nanti atau gunakan Chat untuk memahami langkah berikutnya." : "Check back later or use Chat to understand your next step."}</p>
      <div className={pageStyles.stateActions}><Link className={uiStyles.button} href="/student/chat">{lang === "id" ? "Buka Chat" : "Open Chat"}</Link></div>
    </WorkspaceState>}
    {list.ok && await Promise.all(list.data.map(item => <ObligationCard key={item.id} item={item} lang={lang}
      pending={pending.find(intent => intent.obligation_id === item.id)} />))}
    {documents.ok && documents.data.length > 0 && <UntrustedDocuments documents={documents.data} lang={lang} />}
  </main></>;
}

async function ObligationCard(
  { item, lang, pending }: { item: Schema["TuitionObligationDetail"]; lang: "en" | "id"; pending?: Schema["PaymentIntentView"] },
) {
  const transferId = item.provider_status?.payment_id;
  const topup = item.state === "PARTIALLY_POSTED" && item.topup_permitted && item.shortfall_minor > 0;
  const revisable = pending?.state === "AWAITING_APPROVAL" || pending?.state === "AUTHORIZED";
  const mode = pending ? (revisable ? "revise" : null) : item.state === "UNPAID" ? "create" : topup ? "topup" : null;
  const [payment, quotes, options, transferTrail, intentTrail] = await Promise.all([
    transferId ? financeGet<Schema["PaymentResult"]>(`/api/v1/transfers/${transferId}`) : null,
    mode ? financeGet<Schema["FxQuote"][]>(`/api/v1/quotes?obligation_id=${item.id}`) : null,
    mode ? financeGet<Schema["PaymentOptions"]>(`/api/v1/tuition/obligations/${item.id}/payment-options`) : null,
    transferId ? financeGet<Schema["AuditEntry"][]>(`/api/v1/audit?resource_id=${transferId}`) : null,
    pending ? financeGet<Schema["AuditEntry"][]>(`/api/v1/audit?resource_id=${pending.id}`) : null,
  ]);
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
      <h3>{paymentStateLabels[pending.state][lang]}</h3>
      <IntentSummary intent={pending} lang={lang} />
      {pending.state === "AWAITING_APPROVAL" && <p className={styles.notice}>{ui.waitingOwner[lang]}</p>}
      {pending.state === "ON_HOLD" && <p className={styles.notice} role="alert">
        {safeNextStep[pending.hold_reason ?? "SECURITY_HOLD"][lang]}
      </p>}
      <IntentActions lang={lang} intentId={pending.id} canContinue={pending.state === "AUTHORIZED"}
        payee={pending.beneficiary_label} total={money(pending.source_currency, pending.source_total_minor)}
        canRequestApproval={pending.state === "AWAITING_APPROVAL"} />
    </section>}
    {item.state !== "PAID" && item.state !== "UNPAID" && <p className={styles.notice}>{ui.noPay[lang]}</p>}
    {payment?.ok && <ReceiptCard payment={payment.data} lang={lang} />}
    {quotes?.ok && quotes.data.length > 0 && <QuoteBreakdown quotes={quotes.data} lang={lang} />}
    {mode && quotes?.ok && options?.ok && <RouteChoices lang={lang} mode={mode} obligationId={item.id}
      currentIntentId={pending?.id} currentQuoteId={pending?.quote_id}
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
