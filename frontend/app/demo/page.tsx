import { dateTime } from "../student/chat/chat-types";
import { SimulatedBanner } from "../student/payments/components";
import { type Schema, financeGet } from "../student/payments/finance-api";
import styles from "../student/payments/payments.module.css";
import { pickLang, ui } from "../student/payments/status-labels";
import { DemoControls } from "./controls";

export const metadata = { title: "Demo controls | Rantau" };
export const dynamic = "force-dynamic";

const adminOnly = { en: "Demo administrator sign-in is required.", id: "Perlu masuk sebagai administrator demo." };
const trailTitle = { en: "Redacted audit trail (current run)", id: "Jejak audit tersamar (sesi saat ini)" };

export default async function DemoPage({ searchParams }: { searchParams: Promise<{ lang?: string }> }) {
  const lang = pickLang((await searchParams).lang);
  const scenarios = await financeGet<Schema["ScenarioInfo"][]>("/api/v1/demo/scenarios");
  if (!scenarios.ok) {
    return <main className={styles.page}>
      <SimulatedBanner lang={lang} />
      <p className={styles.notice} role="alert">
        {scenarios.reason === "unavailable" ? ui.unavailable[lang] : adminOnly[lang]}
      </p>
    </main>;
  }
  const trail = await financeGet<Schema["AuditEntry"][]>("/api/v1/demo/audit");
  return <main className={styles.page}>
    <SimulatedBanner lang={lang} />
    <h1>Demo</h1>
    <DemoControls scenarios={scenarios.data} />
    <section className={styles.card}>
      <h2>{trailTitle[lang]}</h2>
      <table className={styles.table}>
        <thead><tr><th>Time</th><th>Action</th><th>Resource</th><th>Decision</th><th>Reason</th></tr></thead>
        <tbody>{trail.ok && trail.data.map(entry => <tr key={entry.audit_event_id}>
          <td>{dateTime(entry.created_at)}</td><td>{entry.action}</td>
          <td>{entry.resource_id ?? "-"}</td><td>{entry.decision ?? "-"}</td><td>{entry.reason_code ?? "-"}</td>
        </tr>)}</tbody>
      </table>
    </section>
  </main>;
}
