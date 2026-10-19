import Link from "next/link";
import styles from "./ui.module.css";

export function Brand() {
  return <Link href="/" className={styles.brand} aria-label="Rantau home" translate="no">rantau<span aria-hidden="true">↗</span></Link>;
}

type NavLink = { href: string; label: string; current?: boolean };
function Navigation({ links, label, className }: { links: NavLink[]; label: string; className?: string }) {
  return <nav aria-label={label} className={className}>{links.map(link =>
    <Link key={link.href} href={link.href} prefetch={false} aria-current={link.current ? "page" : undefined}>{link.label}</Link>
  )}</nav>;
}
export function WorkspaceHeader({ links, label, children, primaryLinks }: {
  links: NavLink[]; label: string; children?: React.ReactNode; primaryLinks?: NavLink[];
}) {
  return <header className={styles.header}><div className={styles.headerInner}>
    <Brand />
    {primaryLinks && <Navigation links={primaryLinks} label="Chat views" className={styles.viewTabs} />}
    <div className={styles.headerActions}><Navigation links={links} label={label} />{children}</div>
  </div></header>;
}

export function StudentHeader({ current, payments = false, lang = "en" }: {
  current?: "chat" | "scenarios" | "payments" | "account"; payments?: boolean; lang?: "en" | "id";
}) {
  return <WorkspaceHeader label="Student workspace" primaryLinks={[
    { href: "/student/chat", label: "Chat", current: current === "chat" },
    { href: "/student/chat/preview", label: "Scenarios", current: current === "scenarios" },
  ]} links={[
    { href: `/student/payments${lang === "id" ? "?lang=id" : ""}`, label: lang === "id" ? "Pembayaran" : "Payments", current: payments || current === "payments" },
    { href: "/student/sign-in", label: lang === "id" ? "Masuk / akun" : "Sign in / account", current: current === "account" },
  ]} />;
}
