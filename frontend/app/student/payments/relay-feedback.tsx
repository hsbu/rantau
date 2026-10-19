"use client";

import type { Lang } from "./status-labels";
import { ui } from "./status-labels";
import styles from "../../components/ui.module.css";

export function RelayFeedback({ busy, message, uncertain, lang }: { busy: boolean; message: string | null; uncertain: boolean; lang: Lang }) {
  return <>
    {busy && <p role="status">{ui.processing[lang]}</p>}
    {message && <div role="alert" className={styles.notice}><p>{message}</p>
      {uncertain && <button type="button" className={`${styles.button} ${styles.secondary}`} onClick={() => window.location.reload()}>{ui.checkStatus[lang]}</button>}
    </div>}
  </>;
}
