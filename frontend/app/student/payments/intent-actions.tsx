"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import styles from "./payments.module.css";
import { type Lang, safeNextStep, ui } from "./status-labels";

type Props = { lang: Lang; intentId: string; canContinue: boolean };

export function IntentActions({ lang, intentId, canContinue }: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function run(action: "cancel-intent" | "execute-intent") {
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(`/student/payments/api/${action}`, {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: intentId }),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        const code = error?.reason_code as keyof typeof safeNextStep | undefined;
        setMessage(code && safeNextStep[code] ? safeNextStep[code][lang] : ui.unavailable[lang]);
      }
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  return <div>
    <div className={styles.actions}>
      {canContinue && <button disabled={busy} onClick={() => run("execute-intent")}>{ui.continueIntent[lang]}</button>}
      <button disabled={busy} onClick={() => run("cancel-intent")}>{ui.cancelIntent[lang]}</button>
    </div>
    {message && <p className={styles.notice} role="alert">{message}</p>}
  </div>;
}
