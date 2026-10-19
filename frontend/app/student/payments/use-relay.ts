"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { type Lang, safeNextStep, ui } from "./status-labels";

// One place for relay calls: show a safe next step for a refusal, then refresh server data.
export function useRelay(lang: Lang) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const inFlight = useRef(false);

  async function run(action: string, body: Record<string, string>) {
    if (inFlight.current || uncertain) return;
    inFlight.current = true;
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(`/student/payments/api/${action}`, {
        method: "POST", credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(30000),
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        const code = error?.reason_code as keyof typeof safeNextStep | undefined;
        if (response.status >= 500 || !code || !Object.hasOwn(safeNextStep, code)) {
          setUncertain(true); setMessage(ui.unconfirmed[lang]); return;
        }
        setMessage(safeNextStep[code][lang]);
      }
      router.refresh();
    } catch {
      setUncertain(true); setMessage(ui.unconfirmed[lang]);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return { busy, message, uncertain, run };
}
