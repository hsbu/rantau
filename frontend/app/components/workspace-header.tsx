import Link from "next/link";
import styles from "./ui.module.css";

export function Brand() {
  return <Link href="/" className={styles.brand} aria-label="Rantau home" translate="no">rantau<span aria-hidden="true">↗</span></Link>;
}

type NavLink = { href: string; label: string; current?: boolean };
export function WorkspaceHeader({ links, label, children }: { links: NavLink[]; label: string; children?: React.ReactNode }) {
  return <header className={styles.header}>
    <Brand />
    <div className={styles.headerActions}><nav aria-label={label}>
      {links.map(link => <Link key={link.href} href={link.href} aria-current={link.current ? "page" : undefined}>{link.label}</Link>)}
    </nav>{children}</div>
  </header>;
}

export function StudentHeader({ payments = false, lang = "en" }: { payments?: boolean; lang?: "en" | "id" }) {
  return <WorkspaceHeader label="Student workspace" links={[
    { href: "/student/chat", label: "Chat" },
    { href: `/student/payments${lang === "id" ? "?lang=id" : ""}`, label: lang === "id" ? "Pembayaran" : "Payments", current: payments },
    { href: "/student/sign-in", label: lang === "id" ? "Masuk / akun" : "Sign in / account" },
  ]} />;
}
