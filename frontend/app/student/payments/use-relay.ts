"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { type Lang, safeNextStep, ui } from "./status-labels";

// One place for relay calls: show a safe next step for a refusal, then refresh server data.
export function useRelay(lang: Lang) {
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
        setMessage(code && safeNextStep[code] ? safeNextStep[code][lang] : ui.unavailable[lang]);
      }
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  return { busy, message, run };
}
