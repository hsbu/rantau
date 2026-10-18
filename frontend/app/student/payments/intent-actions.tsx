"use client";

import styles from "./payments.module.css";
import { type Lang, ui } from "./status-labels";
import { useRelay } from "./use-relay";

type Props = { lang: Lang; intentId: string; canContinue: boolean; canRequestApproval: boolean };

export function IntentActions({ lang, intentId, canContinue, canRequestApproval }: Props) {
  const { busy, message, run } = useRelay(lang);
  const body = { id: intentId };
  return <div>
    <div className={styles.actions}>
      {canRequestApproval && <button disabled={busy} onClick={() => run("request-approval", body)}>
        {ui.requestApproval[lang]}
      </button>}
      {canContinue && <button disabled={busy} onClick={() => run("execute-intent", body)}>
        {ui.continueIntent[lang]}
      </button>}
      <button disabled={busy} onClick={() => run("cancel-intent", body)}>{ui.cancelIntent[lang]}</button>
    </div>
    {message && <p className={styles.notice} role="alert">{message}</p>}
  </div>;
}
