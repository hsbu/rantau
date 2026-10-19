"use client";

import { useState } from "react";
import { money } from "../chat/chat-types";
import type { Schema } from "./finance-api";
import styles from "./payments.module.css";
import { type Lang, providerLabel, ui } from "./status-labels";
import { RelayFeedback } from "./relay-feedback";
import { useRelay } from "./use-relay";

export type ChoiceMode = "create" | "topup" | "revise";

type Props = {
  lang: Lang;
  mode: ChoiceMode;
  obligationId: string;
  currentIntentId?: string;
  currentQuoteId?: string;
  options: Schema["PaymentOptions"];
  quotes: Schema["FxQuote"][];
};

const BUTTON: Record<ChoiceMode, keyof typeof ui> = {
  create: "chooseRoute", topup: "requestTopup", revise: "changeRoute",
};

// The server re-validates every identifier; this only forwards what the student picked.
export function RouteChoices({ lang, mode, obligationId, currentIntentId, currentQuoteId, options, quotes }: Props) {
  const { busy, message, uncertain, run } = useRelay(lang);
  const [account, setAccount] = useState(options.accounts[0]?.id ?? "");
  const label = ui[BUTTON[mode]] as Record<Lang, string>;

  function choose(quoteId: string) {
    const proposal = {
      obligation_id: obligationId, quote_id: quoteId, source_account_id: account,
      beneficiary_id: options.beneficiary_id,
    };
    return mode === "revise" && currentIntentId
      ? run("revise-intent", { ...proposal, id: currentIntentId })
      : run("create-intent", proposal);
  }

  return <div>
    {options.accounts.length > 1 && <label className={styles.form}>
      {ui.payFrom[lang]}{" "}
      <select value={account} onChange={event => setAccount(event.target.value)} disabled={busy || uncertain}>
        {options.accounts.map(item => <option key={item.id} value={item.id}>
          {item.label} · {item.funded_by_requester ? ui.fundedByYou[lang] : ui.fundedByOwner[lang]}
        </option>)}
      </select>
    </label>}
    <ul className={styles.routes}>
      {quotes.filter(quote => quote.id !== currentQuoteId).map(quote => <li key={quote.id}>
        <span>{providerLabel(quote.provider, lang)} · {money(quote.source_currency, quote.source_total_minor)}</span>
        <button disabled={busy || uncertain} onClick={() => choose(quote.id)}>{label[lang]}</button>
      </li>)}
    </ul>
    <RelayFeedback busy={busy} message={message} uncertain={uncertain} lang={lang} />
  </div>;
}
