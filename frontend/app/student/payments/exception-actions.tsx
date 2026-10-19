"use client";

import styles from "./payments.module.css";
import { type Lang, ui } from "./status-labels";
import { useRelay } from "./use-relay";
import { RelayFeedback } from "./relay-feedback";

type Props = {
  lang: Lang;
  obligationId: string;
  transferId?: string;
  caseId?: string;
  canOpenCase: boolean;
  canSubmitCase: boolean;
};

export function ExceptionActions(props: Props) {
  const { busy, message, uncertain, run } = useRelay(props.lang);
  return <div>
    <div className={styles.actions}>
      <button disabled={busy || uncertain} onClick={() => run("recheck-obligation", { id: props.obligationId })}>
        {ui.recheck[props.lang]}
      </button>
      {props.canOpenCase && props.transferId && <button disabled={busy || uncertain}
        onClick={() => run("open-case", { transfer_id: props.transferId!, obligation_id: props.obligationId })}>
        {ui.openCase[props.lang]}
      </button>}
      {props.canSubmitCase && props.caseId && <button disabled={busy || uncertain}
        onClick={() => run("submit-case", { id: props.caseId! })}>
        {ui.submitCase[props.lang]}
      </button>}
    </div>
    <RelayFeedback busy={busy} message={message} uncertain={uncertain} lang={props.lang} />
  </div>;
}
