"use client";

import { useEffect, useId, useRef } from "react";
import styles from "./ui.module.css";

export function ConfirmationDialog({ open, title, children, confirmLabel, cancelLabel, onConfirm, onCancel, lang = "en" }: {
  open: boolean; title: string; children: React.ReactNode; confirmLabel: string; cancelLabel: string;
  onConfirm: () => void; onCancel: () => void; lang?: "en" | "id";
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  useEffect(() => {
    if (!open || !dialog.current) return;
    const element = dialog.current;
    const trigger = document.activeElement;
    element.showModal();
    return () => {
      element.close();
      if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus();
    };
  }, [open]);
  return open && <dialog ref={dialog} className={styles.dialog} lang={lang} aria-labelledby={titleId} aria-describedby={descriptionId}
    onCancel={event => { event.preventDefault(); onCancel(); }}>
    <div className={styles.dialogContent}>
      <h2 id={titleId}>{title}</h2>
      <div id={descriptionId}>{children}</div>
      <div className={styles.dialogActions}>
        <button type="button" className={`${styles.button} ${styles.secondary}`} onClick={onCancel}>{cancelLabel}</button>
        <button type="button" className={styles.button} onClick={onConfirm}>{confirmLabel}</button>
      </div>
    </div>
  </dialog>;
}
