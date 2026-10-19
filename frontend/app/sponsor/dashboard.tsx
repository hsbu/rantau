"use client";

import { ApprovalSummary, type SummaryLanguage } from "./approval-summary";

import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { components } from "../../lib/api-contracts/generated";
import Link from "next/link";
import { WorkspaceHeader } from "../components/workspace-header";
import { CredentialsFields, validateCredentials, type FieldErrors } from "../components/credentials-fields";
import uiStyles from "../components/ui.module.css";
import styles from "./sponsor.module.css";

type Approval = components["schemas"]["ApprovalView"];
type Session = components["schemas"]["SessionSummary"];
type DecisionResult = components["schemas"]["SponsorDecisionResult"];
type Decision = components["schemas"]["SponsorDecisionRequest"]["decision"];
type SecurityCase = components["schemas"]["SecurityCaseView"];
type Mode = "checking" | "signed-out" | "wrong-role" | "ready";

const identifier = /^[A-Za-z0-9_.:-]{1,128}$/;
const digest = /^[0-9a-f]{64}$/;
const approvalStates = new Set<Approval["state"]>([
  "REQUESTED", "PENDING", "APPROVED", "REJECTED", "EXPIRED", "REVOKED",
  "INVALIDATED_BY_CHANGE", "CONSUMED",
]);
const caseStates = new Set<SecurityCase["state"]>([
  "OPEN", "UNDER_REVIEW", "RESOLVED", "ESCALATED",
]);
const caseReasons = new Set<SecurityCase["reason"]>([
  "UNKNOWN_BENEFICIARY", "BENEFICIARY_MISMATCH", "BENEFICIARY_CHANGE_REQUESTED",
  "PROMPT_INJECTION", "SCAM_INDICATOR", "POLICY_REVIEW",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isSession(value: unknown): value is Session {
  return isRecord(value) && value.authenticated === true
    && (value.role === "SPONSOR" || value.role === "STUDENT"
      || value.role === "DEMO_ADMIN" || value.role === "UNIVERSITY_SERVICE");
}

function isApproval(value: unknown): value is Approval {
  if (!isRecord(value)) return false;
  return typeof value.source_label === "string" && value.source_label.length <= 120
    && typeof value.beneficiary_label === "string" && value.beneficiary_label.length <= 120
    && Number.isSafeInteger(value.source_principal_minor) && Number(value.source_principal_minor) >= 0
    && Number.isSafeInteger(value.fee_minor) && Number(value.fee_minor) >= 0
    && typeof value.approval_id === "string" && identifier.test(value.approval_id)
    && typeof value.intent_id === "string" && identifier.test(value.intent_id)
    && Number.isSafeInteger(value.intent_revision) && Number(value.intent_revision) > 0
    && typeof value.terms_hash === "string" && digest.test(value.terms_hash)
    && typeof value.state === "string" && approvalStates.has(value.state as Approval["state"])
    && typeof value.expires_at === "string" && Number.isFinite(Date.parse(value.expires_at))
    && (value.purpose === "TUITION" || value.purpose === "ALLOWANCE")
    && (value.source_currency === "IDR" || value.source_currency === "CNY")
    && (value.destination_currency === "IDR" || value.destination_currency === "CNY")
    && Number.isSafeInteger(value.source_total_minor) && Number(value.source_total_minor) > 0
    && Number.isSafeInteger(value.destination_amount_minor) && Number(value.destination_amount_minor) > 0
    && BigInt(Number(value.source_principal_minor)) + BigInt(Number(value.fee_minor))
      === BigInt(Number(value.source_total_minor))
    && value.simulated === true;
}

function isApprovalList(value: unknown): value is Approval[] {
  return Array.isArray(value) && value.length <= 100 && value.every(isApproval);
}

function isDecisionResult(value: unknown): value is DecisionResult {
  return isRecord(value) && typeof value.approval_id === "string"
    && identifier.test(value.approval_id)
    && (value.decision === "APPROVED" || value.decision === "REJECTED")
    && typeof value.intent_id === "string" && identifier.test(value.intent_id)
    && typeof value.current_terms_hash === "string" && digest.test(value.current_terms_hash)
    && typeof value.recorded_at === "string" && Number.isFinite(Date.parse(value.recorded_at));
}

function isSecurityCase(value: unknown): value is SecurityCase {
  if (!isRecord(value)) return false;
  return typeof value.case_id === "string" && identifier.test(value.case_id)
    && typeof value.resource_id === "string" && identifier.test(value.resource_id)
    && typeof value.state === "string" && caseStates.has(value.state as SecurityCase["state"])
    && typeof value.reason === "string" && caseReasons.has(value.reason as SecurityCase["reason"])
    && typeof value.created_at === "string" && Number.isFinite(Date.parse(value.created_at))
    && typeof value.updated_at === "string" && Number.isFinite(Date.parse(value.updated_at))
    && typeof value.audit_event_id === "string" && identifier.test(value.audit_event_id);
}

function isSecurityCaseList(value: unknown): value is { cases: SecurityCase[] } {
  return isRecord(value) && Object.keys(value).length === 1 && Object.hasOwn(value, "cases")
    && Array.isArray(value.cases) && value.cases.length <= 100
    && value.cases.every(isSecurityCase);
}

async function errorCode(response: Response): Promise<string> {
  try {
    const value: unknown = await response.json();
    return isRecord(value) && typeof value.code === "string" ? value.code : "";
  } catch { return ""; }
}

function formatExpiry(value: string, language: SummaryLanguage = "en"): string {
  return new Intl.DateTimeFormat(language === "id" ? "id-ID" : "en-GB", {
    dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Shanghai",
  }).format(new Date(value)) + " (UTC+08:00)";
}

function humanise(value: string): string {
  return value.replaceAll("_", " ").toLowerCase();
}

export function SponsorDashboard() {
  const [language, setLanguage] = useState<SummaryLanguage>("en");
  const [mode, setMode] = useState<Mode>("checking");
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [cases, setCases] = useState<SecurityCase[]>([]);
  const [casesNotice, setCasesNotice] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [busyId, setBusyId] = useState<string>();
  const [confirmation, setConfirmation] = useState<{ item: Approval; decision: Decision }>();
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [uncertain, setUncertain] = useState(false);
  const confirmationDialog = useRef<HTMLDialogElement>(null);

  const loadInbox = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/sponsor/api/approvals", {
        credentials: "same-origin", cache: "no-store",
      });
      if (response.status === 401) {
        setMode("signed-out");
        setApprovals([]);
        setError("Your session has expired. Sign in again to continue.");
        return false;
      }
      if (!response.ok) {
        const code = await errorCode(response);
        setError(code === "SERVICE_UNAVAILABLE"
          ? "Approval services are unavailable right now. Your requests have not been changed."
          : "We could not refresh approvals. Try again shortly.");
        return false;
      }
      const value: unknown = await response.json();
      if (!isApprovalList(value)) throw new Error("Invalid approval response");
      setApprovals(value);
      setUncertain(false);
      return true;
    } catch {
      setError("We could not confirm the approval list. Refresh before making another decision.");
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  const loadCases = useCallback(async () => {
    setCasesNotice("");
    try {
      const response = await fetch("/sponsor/api/cases", {
        credentials: "same-origin", cache: "no-store",
      });
      if (response.status === 401) {
        setCases([]);
        setCasesNotice("Your session expired. Sign in again to see security cases.");
        return;
      }
      if (!response.ok) {
        setCases([]);
        setCasesNotice("Security cases are unavailable right now. Your payment states are unchanged.");
        return;
      }
      const value: unknown = await response.json();
      if (!isSecurityCaseList(value)) throw new Error("Invalid security case response");
      setCases(value.cases);
    } catch {
      setCases([]);
      setCasesNotice("We could not confirm the security case list. Refresh to try again.");
    }
  }, []);

  const checkSession = useCallback(async () => {
    setMode("checking");
    try {
      const response = await fetch("/sponsor/api/session", {
        credentials: "same-origin", cache: "no-store",
      });
      if (response.status === 401) {
        setMode("signed-out");
        return;
      }
      if (!response.ok) {
        setMode("signed-out");
        setError("Sign-in is temporarily unavailable. Please try again later.");
        return;
      }
      const value: unknown = await response.json();
      if (!isSession(value)) throw new Error("Invalid session response");
      if (value.role !== "SPONSOR") {
        setMode("wrong-role");
        setApprovals([]);
        setCases([]);
        return;
      }
      setMode("ready");
      await Promise.all([loadInbox(), loadCases()]);
    } catch {
      setMode("signed-out");
      setError("We could not check your session. Please try again.");
    }
  }, [loadInbox, loadCases]);

  useEffect(() => { void checkSession(); }, [checkSession]);

  useEffect(() => {
    const dialog = confirmationDialog.current;
    if (!dialog || !confirmation) return;
    dialog.showModal();
    return () => { if (dialog.open) dialog.close(); };
  }, [confirmation]);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const validation = validateCredentials(event.currentTarget, username, password);
    setFieldErrors(validation);
    if (validation.username || validation.password) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch("/sponsor/api/login", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      setPassword("");
      if (response.status === 401) {
        setError("Those sign-in details were not accepted.");
        return;
      }
      if (response.status === 429) {
        setError("Too many sign-in attempts. Please wait before trying again.");
        return;
      }
      if (!response.ok) {
        setError("Sign-in is unavailable. Try again later.");
        return;
      }
      const value: unknown = await response.json();
      if (!isSession(value)) throw new Error("Invalid session response");
      if (value.role !== "SPONSOR") {
        setMode("wrong-role");
        setApprovals([]);
        setCases([]);
        return;
      }
      setMode("ready");
      setNotice("Signed in. Review each request before choosing a decision.");
      await Promise.all([loadInbox(), loadCases()]);
    } catch {
      setError("We could not confirm sign-in. Check the session before trying again.");
    } finally {
      setPassword("");
      setBusy(false);
    }
  }

  async function signOut() {
    setBusy(true);
    try {
      const response = await fetch("/sponsor/api/logout", {
        method: "POST", credentials: "same-origin", cache: "no-store",
      });
      if (!response.ok && response.status !== 401) {
        setError("Sign-out could not be confirmed. Please try again.");
        return;
      }
      setApprovals([]);
      setCases([]);
      setCasesNotice("");
      setConfirmation(undefined);
      setPassword("");
      setNotice("");
      setError("");
      setMode("signed-out");
    } catch {
      setError("Sign-out could not be confirmed. Please try again.");
    } finally { setBusy(false); }
  }

  async function decide(item: Approval, decision: Decision) {
    if (busy || uncertain || item.state !== "PENDING") return;
    setBusy(true);
    setBusyId(item.approval_id);
    setError("");
    setNotice("");
    setConfirmation(undefined);
    try {
      const response = await fetch(
        `/sponsor/api/approvals/${encodeURIComponent(item.approval_id)}/decision`,
        {
          method: "POST", credentials: "same-origin", cache: "no-store",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision, terms_hash: item.terms_hash }),
        },
      );
      if (response.status === 401) {
        setApprovals([]);
        setMode("signed-out");
        setError("Your session expired. Sign in again, then refresh approvals.");
        return;
      }
      if (response.status === 409) {
        setNotice("This request changed or expired. The inbox is refreshing; review its current terms.");
        await loadInbox();
        return;
      }
      if (!response.ok) {
        setUncertain(response.status >= 500 || response.status === 404);
        const code = await errorCode(response);
        setError(response.status === 404
          ? "This request is no longer available. Refresh the inbox."
          : code === "SERVICE_UNAVAILABLE"
            ? "The decision could not be confirmed. Refresh the inbox before taking another action."
            : "The decision could not be confirmed. Refresh the inbox before taking another action.");
        return;
      }
      const result: unknown = await response.json();
      if (!isDecisionResult(result) || result.approval_id !== item.approval_id
        || result.decision !== decision || result.current_terms_hash !== item.terms_hash) {
        setUncertain(true);
        setError("The decision response could not be verified. Refresh the inbox before continuing.");
        return;
      }
      setApprovals(current => current.map(entry => entry.approval_id === item.approval_id
        ? { ...entry, state: result.decision } : entry));
      setNotice(`Your ${decision === "APPROVED" ? "approval" : "rejection"} was recorded. This does not mean a payment was made.`);
      await loadInbox();
    } catch {
      setUncertain(true);
      setError("We could not confirm the decision. Refresh the inbox before taking another action.");
    } finally {
      setBusy(false);
      setBusyId(undefined);
    }
  }

  const pending = approvals.filter(item => item.state === "PENDING");
  const history = approvals.filter(item => item.state !== "PENDING");

  return <main id="main-content" tabIndex={-1} className={styles.page}>
    <WorkspaceHeader label="Workspaces" links={[{ href: "/student/sign-in", label: "Student workspace" }]}>
      {mode === "ready" && <button className={`${uiStyles.button} ${uiStyles.secondary}`} onClick={() => void signOut()} disabled={busy}>Sign out</button>}
    </WorkspaceHeader>

    <section className={styles.intro}>
      <p className={styles.eyebrow}>Sponsor workspace</p>
      <h1>Review payment requests</h1>
      <label className={styles.summaryLanguage}>Summary language <select aria-label="Summary language" value={language}
        onChange={event => setLanguage(event.target.value === "id" ? "id" : "en")}><option value="en">English</option><option value="id">Bahasa Indonesia</option></select></label>
      <p className={styles.muted}>Language applies to payment summaries and confirmation. Dates use China time (UTC+08:00).</p>
      <p>Check the recipient and full cost before recording a decision.</p>
      <div className={styles.safety} role="note">
        <span aria-hidden="true">ⓘ</span>
        <p>An approval authorizes an attempt. It does not move money or confirm tuition has been posted.</p>
      </div>
    </section>

    {error && <p id="signin-error" className={styles.error} role="alert">{error}</p>}
    {notice && <p className={styles.notice} role="status">{notice}</p>}

    {mode === "checking" && <div className={styles.loading} role="status">Checking your sponsor session…</div>}
    {mode === "signed-out" && <form className={styles.signIn} onSubmit={signIn} noValidate>
      <div>
        <p className={styles.eyebrow}>Sponsor sign-in</p>
        <h2>Welcome back</h2>
        <p className={styles.muted}>Use the sponsor credentials provided for this simulated environment.</p>
      </div>
      <CredentialsFields username={username} password={password} setUsername={setUsername} setPassword={setPassword}
        busy={busy} errors={fieldErrors} errorId={error ? "signin-error" : undefined} />
      <button className={uiStyles.button} type="submit" disabled={busy}>
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>}
    {mode === "wrong-role" && <section className={styles.signIn}>
      <h2>This workspace is for sponsors</h2>
      <p className={styles.muted}>Your current session does not have a sponsor role.</p>
      <Link href="/student/sign-in">Open student workspace →</Link>
      <button className={styles.primary} onClick={() => void signOut()} disabled={busy}>Sign out</button>
    </section>}

    {mode === "ready" && <div className={styles.dashboard}>
      <section className={styles.section} aria-labelledby="pending-title">
        <div className={styles.sectionHeading}>
          <div><p className={styles.eyebrow}>Needs your review</p><h2 id="pending-title">Pending requests</h2></div>
          <button className={styles.textButton} onClick={() => void loadInbox()} disabled={busy}>Refresh</button>
        </div>
        {pending.length === 0 && !busy && <p className={styles.empty}>No requests are waiting for a decision.</p>}
        {busy && approvals.length === 0 && <p className={styles.loading} role="status">Loading approvals…</p>}
        <div className={styles.cards}>
          {pending.map(item => <ApprovalCard key={item.approval_id} item={item} busy={busy}
            busyId={busyId} uncertain={uncertain} language={language} onChoose={(decision) => setConfirmation({ item, decision })} />)}
        </div>
      </section>

      {history.length > 0 && <section className={styles.section} aria-labelledby="history-title">
        <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Past decisions</p><h2 id="history-title">Request history</h2></div></div>
        <div className={styles.cards}>
          {history.map(item => <ApprovalCard key={item.approval_id} item={item} busy={busy}
            busyId={busyId} uncertain={uncertain} language={language} onChoose={(decision) => setConfirmation({ item, decision })} />)}
        </div>
      </section>}

      <section className={styles.section} aria-labelledby="cases-title">
        <div className={styles.sectionHeading}>
          <div><p className={styles.eyebrow}>Security review</p><h2 id="cases-title">Security cases</h2></div>
          <button className={styles.textButton} onClick={() => void loadCases()}>Refresh</button>
        </div>
        <p className={styles.muted}>Read-only. Clearing a hold or deciding a case happens in a separate trusted
          review and is never available from this page.</p>
        {casesNotice && <p className={styles.error} role="alert">{casesNotice}</p>}
        {!casesNotice && cases.length === 0 &&
          <p className={styles.empty}>No security case is open in your name.</p>}
        <ul className={styles.caseList}>
          {cases.map(item => <li key={item.case_id} className={styles.caseRow}>
            <div>
              <span className={styles.purpose}>{humanise(item.reason)}</span>
              <h3>{item.case_id}</h3>
              <p className={styles.muted}>Related payment {item.resource_id} · opened {formatExpiry(item.created_at)} ·
                updated {formatExpiry(item.updated_at)}</p>
            </div>
            <span className={styles.state}>{humanise(item.state)}</span>
          </li>)}
        </ul>
      </section>
    </div>}

    {confirmation && <dialog ref={confirmationDialog} className={uiStyles.dialog} lang={language}
      aria-labelledby="confirm-title" aria-describedby="confirm-copy"
      onCancel={event => { event.preventDefault(); setConfirmation(undefined); }}>
      <section className={styles.confirm} aria-labelledby="confirm-title" aria-describedby="confirm-copy">
        <p className={styles.eyebrow}>{language === "id" ? "Konfirmasi keputusan Anda" : "Confirm your decision"}</p>
        <h2 id="confirm-title">{language === "id"
          ? confirmation.decision === "APPROVED" ? "Setujui permintaan ini?" : "Tolak permintaan ini?"
          : confirmation.decision === "APPROVED" ? "Approve this request?" : "Reject this request?"}</h2>
        <p id="confirm-copy">{language === "id"
          ? confirmation.decision === "APPROVED" ? "Anda mengizinkan upaya pembayaran kepada" : "Anda menolak permintaan untuk"
          : confirmation.decision === "APPROVED" ? "You are authorizing an attempt to pay" : "You are rejecting the request for"} <strong>{confirmation.item.beneficiary_label}</strong>.</p>
        <ApprovalSummary item={confirmation.item} language={language} />
        <div className={styles.confirmActions}>
          <button className={styles.secondary} onClick={() => setConfirmation(undefined)} disabled={busy}>{language === "id" ? "Kembali" : "Go back"}</button>
          <button className={confirmation.decision === "APPROVED" ? styles.primary : styles.reject}
            onClick={() => void decide(confirmation.item, confirmation.decision)} disabled={busy}>
            {busy ? language === "id" ? "Mencatat…" : "Recording…" : language === "id"
              ? confirmation.decision === "APPROVED" ? "Konfirmasi persetujuan" : "Konfirmasi penolakan"
              : confirmation.decision === "APPROVED" ? "Confirm approval" : "Confirm rejection"}
          </button>
        </div>
      </section>
    </dialog>}

    <footer className={styles.footer}>Rantau is a simulated financial service. No real payment is made here.</footer>
  </main>;
}

function ApprovalCard({ item, busy, busyId, uncertain, language, onChoose }: {
  item: Approval;
  language: SummaryLanguage;
  busy: boolean;
  busyId?: string;
  uncertain: boolean;
  onChoose: (decision: Decision) => void;
}) {
  const actionable = item.state === "PENDING" && !busy && !uncertain;
  return <article className={styles.card}>
    <div className={styles.cardTop}>
      <div><span className={styles.purpose}>{item.purpose === "TUITION" ? "Tuition" : "Allowance"}</span>
        <h3>{item.beneficiary_label}</h3></div>
      <span className={`${styles.state} ${item.state === "PENDING" ? styles.statePending : ""}`}>
        {humanise(item.state)}
      </span>
    </div>
    <ApprovalSummary item={item} language={language} />
    <p className={styles.expiry} lang={language}>{language === "id" ? "Permintaan berakhir" : "Request expires"} {formatExpiry(item.expires_at, language)}</p>
    {item.state === "PENDING" && <div className={styles.cardActions}>
      <button className={styles.secondary} onClick={() => onChoose("REJECTED")} disabled={!actionable}
        aria-label={`Reject request for ${item.beneficiary_label}`}>
        {busyId === item.approval_id ? "Recording…" : "Reject"}
      </button>
      <button className={styles.primary} onClick={() => onChoose("APPROVED")} disabled={!actionable}
        aria-label={`Approve request for ${item.beneficiary_label}`}>
        Approve
      </button>
    </div>}
  </article>;
}
