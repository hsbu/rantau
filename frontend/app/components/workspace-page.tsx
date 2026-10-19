import Link from "next/link";
import type { ReactNode } from "react";
import styles from "./workspace-page.module.css";

export function PageHeading({ eyebrow, title, description, children }: {
  eyebrow: string; title: string; description: string; children?: ReactNode;
}) {
  return <div className={styles.heading}>
    <div><p className={styles.eyebrow}>{eyebrow}</p><h1>{title}</h1><p className={styles.description}>{description}</p></div>
    {children && <div className={styles.toolbar}>{children}</div>}
  </div>;
}

export function PageLanguage({ lang }: { lang: "en" | "id" }) {
  return <nav className={styles.language} aria-label="Page language">
    <Link href="?lang=en" lang="en" aria-current={lang === "en" ? "page" : undefined}>English</Link>
    <Link href="?lang=id" lang="id" aria-current={lang === "id" ? "page" : undefined}>Bahasa Indonesia</Link>
  </nav>;
}

export function WorkspaceState({ label, title, children }: { label: string; title: string; children: ReactNode }) {
  return <section className={styles.state} aria-label={label}>
    <div className={styles.stateIcon} aria-hidden="true"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="5" y="3" width="14" height="18" rx="3" /><path d="M9 8h6M9 12h6M9 16h3" />
    </svg></div>
    <div className={styles.stateContent}><h2>{title}</h2>{children}</div>
  </section>;
}
