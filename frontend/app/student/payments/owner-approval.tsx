"use client";

import { useState } from "react";
import { ConfirmationDialog } from "../../components/confirmation-dialog";
import { ApprovalSummary } from "../../sponsor/approval-summary";
import { dateTime } from "../chat/chat-types";
import type { Schema } from "./finance-api";
import type { Lang } from "./status-labels";
import { useRelay } from "./use-relay";
import { RelayFeedback } from "./relay-feedback";
import styles from "./payments.module.css";

export function OwnerApproval({ approval, lang }: { approval: Schema["ApprovalView"]; lang: Lang }) {
  const [decision, setDecision] = useState<"APPROVED" | "REJECTED" | null>(null);
  const { busy, message, uncertain, run } = useRelay(lang);
  const approving = decision === "APPROVED";
  return <section aria-label={lang === "id" ? "Persetujuan rekening Anda" : "Your account approval"}>
    <h3>{lang === "id" ? "Tinjau pembayaran dari rekening Anda" : "Review payment from your account"}</h3>
    <ApprovalSummary item={approval} language={lang} />
    <p>{lang === "id" ? "Persetujuan berakhir" : "Approval expires"}: {dateTime(approval.expires_at)}</p>
    <div className={styles.actions}>
      <button disabled={busy || uncertain} onClick={() => setDecision("REJECTED")}>{lang === "id" ? "Tolak pembayaran ini" : "Reject this payment"}</button>
      <button disabled={busy || uncertain} onClick={() => setDecision("APPROVED")}>{lang === "id" ? "Setujui dari rekening saya" : "Approve from my account"}</button>
    </div>
    <ConfirmationDialog open={decision !== null} lang={lang}
      title={lang === "id" ? (approving ? "Setujui pembayaran ini?" : "Tolak pembayaran ini?") : (approving ? "Approve this payment?" : "Reject this payment?")}
      cancelLabel={lang === "id" ? "Kembali" : "Go back"}
      confirmLabel={lang === "id" ? (approving ? "Konfirmasi persetujuan" : "Konfirmasi penolakan") : (approving ? "Confirm approval" : "Confirm rejection")}
      onCancel={() => setDecision(null)} onConfirm={() => {
        const selected = decision; setDecision(null);
        if (selected) void run("owner-decision", { id: approval.approval_id, decision: selected, terms_hash: approval.terms_hash });
      }}>
      <p>{approval.beneficiary_label}</p>
      <ApprovalSummary item={approval} language={lang} />
      <p>{lang === "id" ? "Keputusan ini hanya berlaku untuk rincian di atas. Persetujuan tidak mengirim dana." : "This decision applies only to these exact terms. Approval does not send funds."}</p>
    </ConfirmationDialog>
    <RelayFeedback busy={busy} message={message} uncertain={uncertain} lang={lang} />
  </section>;
}
