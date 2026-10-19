import type { ReactNode } from "react";
import styles from "./sign-in.module.css";

export function SignInLayout({ role, title, description, children }: {
  role: "Student" | "Sponsor"; title: ReactNode; description: string; children: ReactNode;
}) {
  return <main id="main-content" tabIndex={-1} className={styles.page}>
    <div className={styles.layout}>
      <section className={styles.intro} aria-labelledby="workspace-title">
        <p className={styles.eyebrow}>{role} workspace</p>
        <h1 id="workspace-title">{title}</h1>
        <p className={styles.description}>{description}</p>
        <p className={styles.notice}>All payments, quotes and university records are simulated.</p>
      </section>
      <section className={styles.panel} aria-labelledby="sign-in-title">
        <h2 id="sign-in-title">{role} sign-in</h2>
        <p>Use the {role.toLowerCase()} credentials provided for this simulated environment.</p>
        {children}
      </section>
    </div>
  </main>;
}
