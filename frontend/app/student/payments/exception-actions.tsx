"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import styles from "./payments.module.css";
import { type Lang, safeNextStep, ui } from "./status-labels";

type Props = {
  lang: Lang;
  obligationId: string;
  transferId?: string;
  caseId?: string;
  canOpenCase: boolean;
  canSubmitCase: boolean;
};

export function ExceptionActions(props: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function run(action: string, body: Record<string, string>) {
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(`/student/payments/api/${action}`, {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        const code = error?.reason_code as keyof typeof safeNextStep | undefined;
        setMessage(code && safeNextStep[code] ? safeNextStep[code][props.lang] : ui.unavailable[props.lang]);
      }
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  return <div>
    <div className={styles.actions}>
      <button disabled={busy} onClick={() => run("recheck-obligation", { id: props.obligationId })}>
        {ui.recheck[props.lang]}
      </button>
      {props.canOpenCase && props.transferId && <button disabled={busy}
        onClick={() => run("open-case", { transfer_id: props.transferId!, obligation_id: props.obligationId })}>
        {ui.openCase[props.lang]}
      </button>}
      {props.canSubmitCase && props.caseId && <button disabled={busy}
        onClick={() => run("submit-case", { id: props.caseId! })}>
        {ui.submitCase[props.lang]}
      </button>}
    </div>
    {message && <p className={styles.notice} role="alert">{message}</p>}
  </div>;
}
