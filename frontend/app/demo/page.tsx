import { dateTime } from "../student/chat/chat-types";
import { SimulatedBanner, TableScroll } from "../student/payments/components";
import { type Schema, financeGet } from "../student/payments/finance-api";
import styles from "../student/payments/payments.module.css";
import { pickLang, ui } from "../student/payments/status-labels";
import { DemoControls } from "./controls";
import Link from "next/link";
import { WorkspaceHeader } from "../components/workspace-header";

export const metadata = { title: "Demo controls | Rantau" };
export const dynamic = "force-dynamic";

const adminOnly = { en: "Demo administrator sign-in is required.", id: "Perlu masuk sebagai administrator demo." };
const trailTitle = { en: "Redacted audit trail (current run)", id: "Jejak audit tersamar (sesi saat ini)" };

export default async function DemoPage({ searchParams }: { searchParams: Promise<{ lang?: string }> }) {
  const lang = pickLang((await searchParams).lang);
  const scenarios = await financeGet<Schema["ScenarioInfo"][]>("/api/v1/demo/scenarios");
  if (!scenarios.ok) {
    return <main id="main-content" tabIndex={-1} lang={lang} className={styles.page}>
      <WorkspaceHeader label="Demo workspace" links={[{ href: "/", label: "Home" }]} />
      <SimulatedBanner lang={lang} />
      <h1>Demo</h1>
      <p className={styles.notice} role="alert">
        {scenarios.reason === "unavailable" ? ui.unavailable[lang] : adminOnly[lang]}
      </p>
      <p>{lang === "id" ? "Akses demo disediakan oleh administrator Anda." : "Demo access is provided by your administrator."}</p>
      <Link href="/">{lang === "id" ? "Kembali ke beranda" : "Return home"}</Link>
    </main>;
  }
  const trail = await financeGet<Schema["AuditEntry"][]>("/api/v1/demo/audit");
  const current = await financeGet<Schema["DemoState"]>("/api/v1/demo/state");
  return <main id="main-content" tabIndex={-1} lang={lang} className={styles.page}>
    <WorkspaceHeader label="Demo workspace" links={[{ href: "/", label: "Home" }, { href: "/student/chat", label: "Student workspace" }]} />
    <SimulatedBanner lang={lang} />
    <h1>Demo</h1>
    <section className={styles.card} aria-label="Active scenario">
      <h2>Active scenario</h2>
      {current.ok ? <p>{current.data.scenario_id
        ? <><strong>{current.data.scenario_id}</strong> · Run {current.data.run_no}</>
        : "No scenario has been initialized."}</p>
        : <p role="alert">Current scenario state is unavailable. Refresh before operating controls.</p>}
      <p>This is the observed sandbox run. The selector below chooses the next reset.</p>
    </section>
    <DemoControls scenarios={scenarios.data} />
    <section className={styles.card}>
      <h2>{trailTitle[lang]}</h2>
      <TableScroll label={trailTitle[lang]}><table className={styles.table}>
        <thead><tr><th>Time</th><th>Action</th><th>Resource</th><th>Decision</th><th>Reason</th></tr></thead>
        <tbody>{trail.ok && trail.data.map(entry => <tr key={entry.audit_event_id}>
          <td>{dateTime(entry.created_at)}</td><td>{entry.action}</td>
          <td>{entry.resource_id ?? "-"}</td><td>{entry.decision ?? "-"}</td><td>{entry.reason_code ?? "-"}</td>
        </tr>)}</tbody>
      </table></TableScroll>
    </section>
  </main>;
}
