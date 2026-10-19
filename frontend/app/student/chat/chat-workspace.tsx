"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ActionPanel } from "./action-panel";
import { ChatError, visibleText } from "./chat-types";
import { connectedTransport } from "./connected-transport";
import { MessageContent } from "./message-content";
import type { ActionSummary, ChatTransport } from "./chat-types";
import styles from "./chat.module.css";

type Message = { id: number; role: "user" | "assistant"; text: string };
const defaultPrompts = ["Help me pay my tuition", "Has my tuition been credited?", "Something went wrong with my payment"];
const errorText = {
  session: "Your session is unavailable or has expired. Sign in again before continuing. This chat has been cleared for privacy.",
  unavailable: "The agent service is unavailable. If you confirmed or continued a payment, check its status in Payments before retrying. You can also explore the sample conversation.",
  invalid: "The service returned an unreadable response. No financial outcome can be confirmed. Check the original request status before repeating a payment request.",
  uncertain: "We could not confirm the response. Check the original request status before repeating a financial request. This message was not retried automatically.",
};

export function ChatWorkspace({ transport = connectedTransport, preview = false, prompts = defaultPrompts, children }: {
  transport?: ChatTransport; preview?: boolean; prompts?: string[]; children?: React.ReactNode;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [summary, setSummary] = useState<ActionSummary>();
  const [detailsUnavailable, setDetailsUnavailable] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<keyof typeof errorText>();
  const [showLatest, setShowLatest] = useState(false);
  const conversation = useRef<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const input = useRef<HTMLTextAreaElement>(null);
  const transcript = useRef<HTMLDivElement>(null);
  const following = useRef(true);

  useEffect(() => () => { request.current?.abort(); }, []);
  useEffect(() => {
    const log = transcript.current;
    if (log && following.current) log.scrollTop = messages.length || error ? log.scrollHeight : 0;
  }, [messages, busy, error]);

  function latest() {
    following.current = true;
    setShowLatest(false);
    if (transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight;
  }

  function reset() {
    sequence.current++;
    request.current?.abort();
    request.current = null;
    transport.reset?.();
    conversation.current = null;
    following.current = true;
    setShowLatest(false);
    setMessages([]); setSummary(undefined); setDetailsUnavailable(false); setDraft(""); setBusy(false); setError(undefined);
    input.current?.focus({ preventScroll: true });
  }

  async function send(text: string) {
    if (request.current || !text.trim() || text.length > 4000) return;
    following.current = true;
    setShowLatest(false);
    conversation.current ??= crypto.randomUUID();
    const id = ++sequence.current;
    const controller = new AbortController();
    request.current = controller;
    const timer = setTimeout(() => controller.abort(), 30000);
    setBusy(true); setError(undefined); setDraft("");
    // Do not leave a previous quote looking current while a new turn is being evaluated.
    setSummary(undefined);
    setDetailsUnavailable(false);
    setMessages(previous => [...previous, { id, role: "user", text: text.trim() }]);
    try {
      const result = await transport.send({ message: text.trim(), conversation_id: conversation.current }, controller.signal);
      if (sequence.current !== id) return;
      setMessages(previous => [...previous, { id, role: "assistant", text: result.response.message }]);
      setSummary(result.summary);
      setDetailsUnavailable(!!result.detailsUnavailable);
    } catch (failure) {
      if (sequence.current !== id) return;
      const kind = failure instanceof ChatError ? failure.kind : "uncertain";
      setError(kind);
      if (kind === "session") { setMessages([]); setSummary(undefined); conversation.current = null; }
    } finally {
      clearTimeout(timer);
      if (sequence.current === id) { request.current = null; setBusy(false); input.current?.focus({ preventScroll: true }); }
    }
  }

  const promptIndex = Math.min(messages.filter(message => message.role === "user").length, prompts.length - 1);
  return <div className={styles.workspace}>
    <header className={styles.nav}>
      <Link href="/" className={styles.wordmark}>rantau<span aria-hidden="true">↗</span></Link>
      <nav className={styles.viewTabs} aria-label="Chat views">
        <Link href="/student/chat" className={styles.viewTab} aria-current={!preview ? "page" : undefined}>Chat</Link>
        <Link href="/student/chat/preview" className={styles.viewTab} aria-current={preview ? "page" : undefined}>Scenarios</Link>
      </nav>
      {!preview && <nav className={styles.workspaceLinks} aria-label="Student workspace">
        <Link href="/student/payments">Payments</Link><Link href="/student/sign-in">Sign in / account</Link>
      </nav>}
    </header>
    <div className={styles.safetyBanner}>{preview
      ? <>Scenario preview · Scripted responses, no model calls, authentication or payment actions.</>
      : <>Sandbox · No real funds move in this workspace.</>}
    </div>
    {children}
    <main className={styles.main}>
      <div className={styles.conversation}>
        <header className={styles.chatHeader}>
          <div><p className={styles.kicker}>A LITTLE CLOSER TO HOME</p><h1>Let’s work through it.</h1><p>Tuition, transfers and the steps in between.</p></div>
          <button type="button" className={styles.newChat} onClick={reset}>New chat <span aria-hidden="true">＋</span></button>
        </header>
        <div ref={transcript} className={styles.messages} role="log" aria-label="Conversation" aria-live="polite" aria-busy={busy} tabIndex={0}
          onScroll={event => {
            const log = event.currentTarget;
            const nearEnd = log.scrollHeight - log.clientHeight - log.scrollTop < 64;
            following.current = nearEnd;
            setShowLatest(messages.length > 0 && !nearEnd);
          }}>
          {!messages.length && <div className={styles.welcome}>
            <div className={styles.agentMark} aria-hidden="true">r</div>
            <h2>One step at a time.</h2>
            <p>I can help you understand what’s due, review a payment route or find out what needs attention.</p>
            <div className={styles.starters}>{(preview ? [prompts[0]] : prompts).map((prompt, index) =>
              <button type="button" key={prompt} onClick={() => void send(prompt)} disabled={busy}>
                <span className={styles.starterNumber}>0{index + 1}</span><span>{prompt}</span><span aria-hidden="true">↗</span>
              </button>)}</div>
          </div>}
          {messages.map(message => <article key={`${message.id}-${message.role}`} className={message.role === "user" ? styles.userMessage : styles.assistantMessage}>
            <span className={styles.messageLabel}>{message.role === "user" ? "You" : "Rantau"}</span>
            {message.role === "assistant" ? <MessageContent text={visibleText(message.text)} /> : <p>{visibleText(message.text)}</p>}
          </article>)}
          {busy && <p role="status" className={styles.loading}>Reviewing your request<span aria-hidden="true"> · · ·</span></p>}
          {error && <div role="alert" aria-label="Chat error" className={styles.error}><strong>{error === "session" ? "Session required" : "Let’s pause here"}</strong><p>{errorText[error]}</p>
            {error === "session" && <Link href="/student/sign-in">Student sign-in →</Link>}
            {error !== "session" && <Link href="/student/payments">Check Payments →</Link>}
            {error === "unavailable" && <Link href="/student/chat/preview">Explore the fixture preview ↗</Link>}</div>}
          {preview && messages.length > 0 && !busy && !error && <button type="button" className={styles.nextPrompt} onClick={() => void send(prompts[promptIndex])}>{prompts[promptIndex]} <span aria-hidden="true">→</span></button>}
        </div>
        {showLatest && <button type="button" className={styles.latest} onClick={latest}>Latest messages ↓</button>}
        <div className={styles.composerArea}>
          <form className={styles.composer} onSubmit={event => { event.preventDefault(); void send(draft); }}>
            <label className={styles.srOnly} htmlFor="chat-message">Message Rantau</label>
            <textarea ref={input} id="chat-message" placeholder="What would you like help with?" value={draft} maxLength={4000} rows={2}
              aria-describedby="composer-hint" disabled={busy} onChange={event => setDraft(event.target.value)}
              onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(draft); } }} />
            <div className={styles.composerBottom}><span>{draft.length > 3500 ? `${draft.length}/4000 characters` : "Shift + Enter for a new line"}</span>
              <button type="submit" disabled={busy || !draft.trim()} aria-label="Send message">Send <span aria-hidden="true">↑</span></button></div>
          </form>
          <p id="composer-hint" className={styles.composerHint}>{preview ? "Each message advances the selected sample scenario. New chat clears your messages." : "Keep account numbers, credentials and private documents out of chat."}</p>
        </div>
      </div>
      <ActionPanel summary={summary} preview={preview} unavailable={detailsUnavailable} />
    </main>
    <footer className={styles.footer}><span>Across borders. With clarity.</span><span>Student workspace · Rantau</span></footer>
  </div>;
}
