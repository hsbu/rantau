"use client";

import styles from "./payments.module.css";
import { type Lang, ui } from "./status-labels";
import { useRelay } from "./use-relay";
import { useState } from "react";
import { ConfirmationDialog } from "../../components/confirmation-dialog";
import { RelayFeedback } from "./relay-feedback";

type Props = { lang: Lang; intentId: string; payee: string; total: string; canContinue: boolean; canRequestApproval: boolean };

export function IntentActions({ lang, intentId, payee, total, canContinue, canRequestApproval }: Props) {
  const { busy, message, uncertain, run } = useRelay(lang);
  const [confirming, setConfirming] = useState(false);
  const body = { id: intentId };
  return <div>
    <div className={styles.actions}>
      {canRequestApproval && <button disabled={busy || uncertain} onClick={() => run("request-approval", body)}>
        {ui.requestApproval[lang]}
      </button>}
      {canContinue && <button disabled={busy || uncertain} onClick={() => run("execute-intent", body)}>
        {ui.continueIntent[lang]}
      </button>}
      <button disabled={busy || uncertain} onClick={() => setConfirming(true)}>{ui.cancelIntent[lang]}</button>
    </div>
    <ConfirmationDialog open={confirming} lang={lang} title={lang === "id" ? "Batalkan permintaan pembayaran?" : "Cancel payment request?"}
      cancelLabel={lang === "id" ? "Kembali" : "Go back"} confirmLabel={lang === "id" ? "Konfirmasi pembatalan" : "Confirm cancellation"}
      onCancel={() => setConfirming(false)} onConfirm={() => { setConfirming(false); void run("cancel-intent", body); }}>
      <p>{lang === "id" ? "Batalkan permintaan kepada" : "Cancel the request to"} <strong>{payee}</strong> — <strong>{total}</strong>?</p>
      <p>{lang === "id" ? "Pembatalan ini tidak menarik kembali pembayaran yang sudah dikirim. Periksa status pembayaran jika hasil sebelumnya belum pasti." : "This does not recall a payment that has already been sent. Check payment status if an earlier outcome is uncertain."}</p>
    </ConfirmationDialog>
    <RelayFeedback busy={busy} message={message} uncertain={uncertain} lang={lang} />
  </div>;
}
