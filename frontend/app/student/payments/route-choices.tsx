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
  currentFundingOwnerSelf?: boolean;
  options: Schema["PaymentOptions"];
  quotes: Schema["FxQuote"][];
};

const BUTTON: Record<ChoiceMode, keyof typeof ui> = {
  create: "chooseRoute", topup: "requestTopup", revise: "changeRoute",
};

// The server re-validates every identifier; this only forwards what the student picked.
export function RouteChoices({ lang, mode, obligationId, currentIntentId, currentQuoteId, currentFundingOwnerSelf, options, quotes }: Props) {
  const { busy, message, uncertain, run } = useRelay(lang);
  const [account, setAccount] = useState(() => {
    if (mode !== "revise") return options.accounts[0]?.id ?? "";
    const matches = options.accounts.filter(item => item.funded_by_requester === currentFundingOwnerSelf);
    return matches.length === 1 ? matches[0].id : "";
  });
  const label = ui[BUTTON[mode]] as Record<Lang, string>;

  function choose(quoteId: string) {
    if (!account) return;
    const proposal = {
      obligation_id: obligationId, quote_id: quoteId, source_account_id: account,
      beneficiary_id: options.beneficiary_id,
    };
    return mode === "revise" && currentIntentId
      ? run("revise-intent", { ...proposal, id: currentIntentId })
      : run("create-intent", proposal);
  }

  return <div>
    {(options.accounts.length > 1 || !account) && <label className={styles.form}>
      {ui.payFrom[lang]}{" "}
      <select value={account} onChange={event => setAccount(event.target.value)} disabled={busy || uncertain}>
        {!account && <option value="">{lang === "id" ? "Pilih rekening dana" : "Choose a funding account"}</option>}
        {options.accounts.map(item => <option key={item.id} value={item.id}>
          {item.label} · {item.funded_by_requester ? ui.fundedByYou[lang] : ui.fundedByOwner[lang]}
        </option>)}
      </select>
    </label>}
    <ul className={styles.routes}>
      {quotes.filter(quote => quote.id !== currentQuoteId).map(quote => <li key={quote.id}>
        <span>{providerLabel(quote.provider, lang)} · {money(quote.source_currency, quote.source_total_minor)}</span>
        <button disabled={busy || uncertain || !account} onClick={() => choose(quote.id)}>{label[lang]}</button>
      </li>)}
    </ul>
    <RelayFeedback busy={busy} message={message} uncertain={uncertain} lang={lang} />
  </div>;
}
