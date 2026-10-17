"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Schema } from "../student/payments/finance-api";
import styles from "../student/payments/payments.module.css";

const PROVIDERS: Schema["FaultRequest"]["provider"][] = ["mock_remit_a", "mock_remit_b"];
const MODES: Schema["FaultMode"][] = [
  "DELAYED_DELIVERY", "TIMEOUT_AFTER_ACCEPT", "TIMEOUT_BEFORE_ACCEPT",
  "UNAVAILABLE", "SHORT_PAYMENT", "REFERENCE_MISSING",
];

export function DemoControls({ scenarios }: { scenarios: Schema["ScenarioInfo"][] }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [scenario, setScenario] = useState(scenarios[0]?.id ?? "");
  const [hours, setHours] = useState(25);
  const [provider, setProvider] = useState(PROVIDERS[0]);
  const [mode, setMode] = useState(MODES[0]);

  async function run(action: string, body: object = {}) {
    setBusy(true);
    try {
      const response = await fetch(`/demo/api/${action}`, {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      setStatus(response.ok ? `${action}: ok` : `${action}: not available (${response.status})`);
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  return <section className={styles.card}>
    <div className={styles.form}>
      <label>Scenario <select value={scenario} onChange={event => setScenario(event.target.value)}>
        {scenarios.map(item => <option key={item.id} value={item.id}>{item.id}</option>)}
      </select></label>
      <button disabled={busy} onClick={() => run("reset", { scenario_id: scenario })}>Reset scenario</button>
    </div>
    <div className={styles.form}>
      <label>Hours <input type="number" min={1} max={720} value={hours}
        onChange={event => setHours(Number(event.target.value))} /></label>
      <button disabled={busy} onClick={() => run("advance-clock", { hours })}>Advance simulated clock</button>
      <button disabled={busy} onClick={() => run("tick")}>University tick</button>
    </div>
    <div className={styles.form}>
      <label>Provider <select value={provider} onChange={event => setProvider(event.target.value as typeof provider)}>
        {PROVIDERS.map(item => <option key={item}>{item}</option>)}
      </select></label>
      <label>Fault <select value={mode} onChange={event => setMode(event.target.value as typeof mode)}>
        {MODES.map(item => <option key={item}>{item}</option>)}
      </select></label>
      <button disabled={busy} onClick={() => run("fault", { provider, mode, remaining: 1 })}>Inject fault</button>
    </div>
    <p role="status">{status}</p>
  </section>;
}
