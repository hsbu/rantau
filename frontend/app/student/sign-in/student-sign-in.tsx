"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import styles from "./student-sign-in.module.css";

type Mode = "checking" | "signed-out" | "student" | "other" | "unavailable";

function sessionMode(value: unknown): Mode {
  if (!value || typeof value !== "object" || !("authenticated" in value)
    || value.authenticated !== true || !("role" in value)) throw new Error("Invalid session");
  if (value.role === "STUDENT") return "student";
  if (["SPONSOR", "DEMO_ADMIN", "UNIVERSITY_SERVICE"].includes(String(value.role))) return "other";
  throw new Error("Invalid session");
}

export function StudentSignIn({ destination }: { destination: "/student/chat" | "/student/payments" }) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("checking");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetch("/sponsor/api/session", { cache: "no-store", credentials: "same-origin", signal: controller.signal })
      .then(async response => {
        if (response.status === 401) { setMode("signed-out"); return; }
        if (!response.ok) throw new Error("Session unavailable");
        setMode(sessionMode(await response.json()));
      }).catch(() => { if (!controller.signal.aborted) setMode("unavailable"); });
    return () => controller.abort();
  }, []);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !username.trim() || !password) return;
    setBusy(true); setError("");
    try {
      const response = await fetch("/sponsor/api/login", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      setPassword("");
      if (response.status === 401) { setError("Those sign-in details were not accepted."); return; }
      if (response.status === 429) { setError("Too many attempts. Please wait before trying again."); return; }
      if (!response.ok) throw new Error("Sign-in unavailable");
      const next = sessionMode(await response.json());
      setMode(next);
      if (next === "student") { router.replace(destination); router.refresh(); }
    } catch {
      setMode("unavailable");
      setError("We could not confirm sign-in. Check your session before trying again.");
    } finally { setPassword(""); setBusy(false); }
  }

  async function signOut() {
    setBusy(true); setError("");
    try {
      const response = await fetch("/sponsor/api/logout", {
        method: "POST", credentials: "same-origin", cache: "no-store",
      });
      if (!response.ok && response.status !== 401) throw new Error("Sign-out unavailable");
      setMode("signed-out"); setPassword(""); router.refresh();
    } catch { setError("Sign-out could not be confirmed. Please try again."); }
    finally { setBusy(false); }
  }

  return <main className={styles.page}>
    <header className={styles.header}><Link href="/" className={styles.brand}>rantau<span aria-hidden="true">↗</span></Link>
      <Link href="/sponsor">Sponsor workspace</Link></header>
    <div className={styles.layout}>
      <div className={styles.intro}><p className="eyebrow">Student workspace</p>
        <h1>A little closer<br />to home.</h1>
        <p>Review what’s due, plan a payment and follow its progress with Rantau.</p>
        <p className={styles.notice}>All payments, quotes and university records are simulated.</p>
      </div>
      <div className={styles.panel}>
        <h2>Student sign-in</h2>
        <p>Use the student credentials provided for this simulated environment.</p>
        {error && <p role="alert" className={styles.error}>{error}</p>}
        {mode === "checking" && <p role="status">Checking your session…</p>}
        {mode === "signed-out" && <form onSubmit={signIn}>
          <label>Username<input name="username" autoComplete="username" required maxLength={64}
            value={username} onChange={event => setUsername(event.target.value)} disabled={busy} /></label>
          <label>Password<input name="password" type="password" autoComplete="current-password" required maxLength={128}
            value={password} onChange={event => setPassword(event.target.value)} disabled={busy} /></label>
          <button type="submit" disabled={busy || !username.trim() || !password}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>}
        {mode === "student" && <><p>You’re signed in as a student.</p>
          <Link className={styles.primary} href={destination}>Continue to {destination.endsWith("payments") ? "Payments" : "Chat"} →</Link>
          <button className={styles.secondary} onClick={() => void signOut()} disabled={busy}>Sign out</button></>}
        {mode === "other" && <><p>This session belongs to another workspace. Sign out to use student credentials.</p>
          <button onClick={() => void signOut()} disabled={busy}>Sign out</button></>}
        {mode === "unavailable" && <><p role="status">Your session could not be checked. No financial action was requested.</p>
          <button onClick={() => window.location.reload()}>Check session again</button></>}
        <Link className={styles.preview} href="/student/chat/preview">Explore scenarios without signing in ↗</Link>
      </div>
    </div>
  </main>;
}
