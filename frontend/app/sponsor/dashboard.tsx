"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { components } from "../../lib/api-contracts/generated";
import Link from "next/link";
import styles from "./sponsor.module.css";

type Approval = components["schemas"]["ApprovalView"];
type Session = components["schemas"]["SessionSummary"];
type DecisionResult = components["schemas"]["SponsorDecisionResult"];
type Decision = components["schemas"]["SponsorDecisionRequest"]["decision"];
type Mode = "checking" | "signed-out" | "wrong-role" | "ready";

const identifier = /^[A-Za-z0-9_.:-]{1,128}$/;
const digest = /^[0-9a-f]{64}$/;
const approvalStates = new Set<Approval["state"]>([
  "REQUESTED", "PENDING", "APPROVED", "REJECTED", "EXPIRED", "REVOKED",
  "INVALIDATED_BY_CHANGE", "CONSUMED",
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

async function errorCode(response: Response): Promise<string> {
  try {
    const value: unknown = await response.json();
    return isRecord(value) && typeof value.code === "string" ? value.code : "";
  } catch { return ""; }
}

function money(currency: "IDR" | "CNY", minor: number): string {
  if (!Number.isSafeInteger(minor) || minor < 0) return "Amount unavailable";
  const value = BigInt(minor);
  const scale = currency === "CNY" ? BigInt(100) : BigInt(1);
  const major = new Intl.NumberFormat("en-US").format(value / scale);
  const fraction = currency === "CNY" ? `.${String(value % scale).padStart(2, "0")}` : "";
  return `${currency} ${major}${fraction}`;
}

function formatExpiry(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium", timeStyle: "short",
  }).format(new Date(value));
}

function stateLabel(state: Approval["state"]): string {
  return state.replaceAll("_", " ").toLowerCase();
}

export function SponsorDashboard() {
  const [mode, setMode] = useState<Mode>("checking");
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [busyId, setBusyId] = useState<string>();
  const [confirmation, setConfirmation] = useState<{ item: Approval; decision: Decision }>();
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
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
        return;
      }
      setMode("ready");
      await loadInbox();
    } catch {
      setMode("signed-out");
      setError("We could not check your session. Please try again.");
    }
  }, [loadInbox]);

  useEffect(() => { void checkSession(); }, [checkSession]);

  useEffect(() => {
    const dialog = confirmationDialog.current;
    if (!dialog || !confirmation) return;
    dialog.showModal();
    return () => { if (dialog.open) dialog.close(); };
  }, [confirmation]);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !username.trim() || !password) return;
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
        return;
      }
      setMode("ready");
      setNotice("Signed in. Review each request before choosing a decision.");
      await loadInbox();
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

  return <main className={styles.page}>
    <header className={styles.header}>
      <Link className={styles.wordmark} href="/">rantau<span>✳</span></Link>
      {mode === "ready" && <button className={styles.textButton} onClick={() => void signOut()} disabled={busy}>Sign out</button>}
    </header>

    <section className={styles.intro}>
      <p className={styles.eyebrow}>Sponsor workspace</p>
      <h1>Review payment requests</h1>
      <p>Check the recipient and full cost before recording a decision.</p>
      <div className={styles.safety} role="note">
        <span aria-hidden="true">ⓘ</span>
        <p>An approval authorizes an attempt. It does not move money or confirm tuition has been posted.</p>
      </div>
    </section>

    {error && <p className={styles.error} role="alert">{error}</p>}
    {notice && <p className={styles.notice} role="status">{notice}</p>}

    {mode === "checking" && <div className={styles.loading} role="status">Checking your sponsor session…</div>}
    {mode === "signed-out" && <form className={styles.signIn} onSubmit={signIn}>
      <div>
        <p className={styles.eyebrow}>Sponsor sign-in</p>
        <h2>Welcome back</h2>
        <p className={styles.muted}>Use the sponsor credentials provided for this simulated environment.</p>
      </div>
      <label>Username
        <input autoComplete="username" name="username" required maxLength={64} value={username}
          onChange={event => setUsername(event.target.value)} disabled={busy} />
      </label>
      <label>Password
        <input autoComplete="current-password" name="password" type="password" required maxLength={128}
          value={password} onChange={event => setPassword(event.target.value)} disabled={busy} />
      </label>
      <button className={styles.primary} type="submit" disabled={busy || !username.trim() || !password}>
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>}
    {mode === "wrong-role" && <section className={styles.signIn}>
      <h2>This workspace is for sponsors</h2>
      <p className={styles.muted}>Your current session does not have a sponsor role.</p>
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
            busyId={busyId} uncertain={uncertain} onChoose={(decision) => setConfirmation({ item, decision })} />)}
        </div>
      </section>

      {history.length > 0 && <section className={styles.section} aria-labelledby="history-title">
        <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Past decisions</p><h2 id="history-title">Request history</h2></div></div>
        <div className={styles.cards}>
          {history.map(item => <ApprovalCard key={item.approval_id} item={item} busy={busy}
            busyId={busyId} uncertain={uncertain} onChoose={(decision) => setConfirmation({ item, decision })} />)}
        </div>
      </section>}
    </div>}

    {confirmation && <dialog ref={confirmationDialog} className={styles.confirmDialog}
      onCancel={event => { event.preventDefault(); setConfirmation(undefined); }}>
      <section className={styles.confirm} aria-labelledby="confirm-title" aria-describedby="confirm-copy">
        <p className={styles.eyebrow}>Confirm your decision</p>
        <h2 id="confirm-title">{confirmation.decision === "APPROVED" ? "Approve this request?" : "Reject this request?"}</h2>
        <p id="confirm-copy">{confirmation.decision === "APPROVED" ? "You are authorizing an attempt to pay" : "You are rejecting the request for"} <strong>{confirmation.item.beneficiary_label}</strong> ({confirmation.item.purpose.toLowerCase()}).</p>
        <dl className={styles.amounts}>
          <div><dt>From</dt><dd>{confirmation.item.source_label}</dd></div>
          <div><dt>Amount</dt><dd>{money(confirmation.item.source_currency, confirmation.item.source_principal_minor)}</dd></div>
          <div><dt>Fee</dt><dd>{money(confirmation.item.source_currency, confirmation.item.fee_minor)}</dd></div>
          <div className={styles.total}><dt>Total debit</dt><dd>{money(confirmation.item.source_currency, confirmation.item.source_total_minor)}</dd></div>
          <div className={styles.destination}><dt>Recipient receives</dt><dd>{money(confirmation.item.destination_currency, confirmation.item.destination_amount_minor)}</dd></div>
        </dl>
        <div className={styles.confirmActions}>
          <button className={styles.secondary} onClick={() => setConfirmation(undefined)} disabled={busy}>Go back</button>
          <button className={confirmation.decision === "APPROVED" ? styles.primary : styles.reject}
            onClick={() => void decide(confirmation.item, confirmation.decision)} disabled={busy}>
            {busy ? "Recording…" : confirmation.decision === "APPROVED" ? "Confirm approval" : "Confirm rejection"}
          </button>
        </div>
      </section>
    </dialog>}

    <footer className={styles.footer}>Rantau is a simulated financial service. No real payment is made here.</footer>
  </main>;
}

function ApprovalCard({ item, busy, busyId, uncertain, onChoose }: {
  item: Approval;
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
        {stateLabel(item.state)}
      </span>
    </div>
    <dl className={styles.amounts}>
      <div><dt>From</dt><dd>{item.source_label}</dd></div>
      <div><dt>Amount</dt><dd>{money(item.source_currency, item.source_principal_minor)}</dd></div>
      <div><dt>Fee</dt><dd>{money(item.source_currency, item.fee_minor)}</dd></div>
      <div className={styles.total}><dt>Total debit</dt><dd>{money(item.source_currency, item.source_total_minor)}</dd></div>
      <div className={styles.destination}><dt>Recipient receives</dt><dd>{money(item.destination_currency, item.destination_amount_minor)}</dd></div>
    </dl>
    <p className={styles.expiry}>Request expires {formatExpiry(item.expires_at)}</p>
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
