import { dateTime } from "../student/chat/chat-types";
import { SimulatedBanner, TableScroll } from "../student/payments/components";
import { type Schema, financeGet } from "../student/payments/finance-api";
import styles from "../student/payments/payments.module.css";
import { pickLang } from "../student/payments/status-labels";
import { DemoControls } from "./controls";
import Link from "next/link";
import { PageHeading, WorkspaceState } from "../components/workspace-page";
import pageStyles from "../components/workspace-page.module.css";
import uiStyles from "../components/ui.module.css";
import { WorkspaceHeader } from "../components/workspace-header";

export const metadata = { title: "Demo controls | Rantau" };
export const dynamic = "force-dynamic";

const adminOnly = { en: "Demo administrator sign-in is required.", id: "Perlu masuk sebagai administrator demo." };
const controlsNote = {
  en: "These controls change the simulator only. They are not available to students, sponsors or the agent, and they never approve or pay anything.",
  id: "Kontrol ini hanya mengubah simulator. Tidak tersedia bagi mahasiswa, sponsor, atau agen, dan tidak pernah menyetujui atau membayar apa pun.",
};
const trailTitle = { en: "Redacted audit trail (current run)", id: "Jejak audit tersamar (sesi saat ini)" };

export default async function DemoPage({ searchParams }: { searchParams: Promise<{ lang?: string }> }) {
  const lang = pickLang((await searchParams).lang);
  const scenarios = await financeGet<Schema["ScenarioInfo"][]>("/api/v1/demo/scenarios");
  if (!scenarios.ok) {
    return <><WorkspaceHeader label="Demo workspace" links={[{ href: "/", label: "Home" }]} /><main id="main-content" tabIndex={-1} lang={lang} className={styles.page}>
      <PageHeading eyebrow={lang === "id" ? "Ruang administrator" : "Administrator workspace"} title="Demo"
        description={lang === "id" ? "Kelola skenario simulasi dalam ruang administrator." : "Manage simulated scenarios in the administrator workspace."} />
      <SimulatedBanner lang={lang} />
      <WorkspaceState label="Demo access" title={scenarios.reason === "unavailable"
        ? lang === "id" ? "Demo belum tersedia." : "Demo is unavailable."
        : lang === "id" ? "Akses administrator diperlukan." : "Administrator access required."}>
      <p role="alert">
        {scenarios.reason === "unavailable"
          ? lang === "id" ? "Kontrol demo belum tersedia. Perbarui status sebelum mengulangi tindakan skenario." : "Demo controls are unavailable right now. Refresh current status before repeating a scenario action."
          : adminOnly[lang]}
      </p>
      <p>{lang === "id" ? "Akses demo disediakan oleh administrator Anda." : "Demo access is provided by your administrator."}</p>
      <div className={pageStyles.stateActions}>
        {scenarios.reason === "unavailable" && <Link className={uiStyles.button} href={`?lang=${lang}`}>{lang === "id" ? "Perbarui status" : "Refresh status"}</Link>}
        <Link className={`${uiStyles.button} ${scenarios.reason === "unavailable" ? uiStyles.secondary : ""}`} href="/">{lang === "id" ? "Kembali ke beranda" : "Return home"}</Link>
      </div>
      </WorkspaceState>
    </main></>;
  }
  const trail = await financeGet<Schema["AuditEntry"][]>("/api/v1/demo/audit");
  const current = await financeGet<Schema["DemoState"]>("/api/v1/demo/state");
  return <><WorkspaceHeader label="Demo workspace" links={[{ href: "/", label: "Home" }, { href: "/student/chat", label: "Student workspace" }]} /><main id="main-content" tabIndex={-1} lang={lang} className={styles.page}>
    <PageHeading eyebrow={lang === "id" ? "Ruang administrator" : "Administrator workspace"} title="Demo"
      description={lang === "id" ? "Siapkan skenario, atur waktu simulasi, dan tinjau jejak audit sesi ini." : "Prepare a scenario, control simulated time and review the current run's audit trail."} />
    <SimulatedBanner lang={lang} />
    <p className={styles.notice}>{controlsNote[lang]}</p>
    <section className={styles.card} aria-label="Active scenario">
      <h2>Active scenario</h2>
      {current.ok ? <p data-run={current.data.run_no}>{current.data.scenario_id
        ? <><strong>{current.data.scenario_id}</strong> {"\u00b7"} Run {current.data.run_no}</>
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
  </main></>;
}
