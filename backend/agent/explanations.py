"""Deterministic display of validated synthetic quotes; never payment authority."""

from datetime import UTC, datetime
from decimal import Decimal

from backend.contracts.enums import CURRENCY_SCALE, Currency
from backend.contracts.models import FxQuote, Money, TuitionObligation


def format_money(money: Money) -> str:
    scale = CURRENCY_SCALE[money.currency]
    major, minor = divmod(money.amount_minor, 10**scale)
    amount = f"{major:,}" if scale == 0 else f"{major:,}.{minor:0{scale}d}"
    return f"{money.currency.value} {amount}"


def utc_time(value: datetime) -> str:
    if value.utcoffset() is None:
        raise ValueError("An aware clock is required")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def explain_tuition_record(obligation: TuitionObligation) -> str:
    expected = format_money(
        Money(currency=obligation.currency, amount_minor=obligation.amount_due_minor)
    )
    posted = format_money(Money(currency=obligation.currency, amount_minor=obligation.posted_minor))
    remaining = format_money(
        Money(currency=obligation.currency, amount_minor=obligation.balance_minor)
    )
    return (
        f"Simulated university tuition record: expected {expected}; posted {posted}; "
        f"remaining {remaining}. These posted funds refer to the university record; "
        "a credit to a student's bank account alone does not establish tuition completion. "
        f"Simulated tuition due date: {utc_time(obligation.due_at)}."
    )


def display_rate(rate: str | Decimal) -> str:
    """Bound display precision without converting exact rates to binary floats."""
    exact = Decimal(rate)
    rounded = format(exact, ".8f").rstrip("0").rstrip(".")
    return rounded if rounded != "0" else format(exact, ".6E")


def comparable_quotes(
    quotes: tuple[FxQuote, ...], destination: Money, now: datetime
) -> tuple[FxQuote, ...]:
    utc_time(now)
    if len({quote.id for quote in quotes}) != len(quotes):
        return ()
    return tuple(
        sorted(
            (
                quote
                for quote in quotes
                if quote.expires_at > now
                and quote.source_currency == Currency.IDR
                and quote.destination_currency == destination.currency == Currency.CNY
                and quote.destination_amount_minor == destination.amount_minor
            ),
            key=lambda quote: (quote.source_total_minor, quote.id),
        )
    )


def explain_quotes(quotes: tuple[FxQuote, ...], destination: Money, now: datetime) -> str:
    current = comparable_quotes(quotes, destination, now)
    if not current:
        return (
            "No current comparable simulated IDR-to-CNY quotes are available for this balance. "
            "Refresh quotes before planning a payment."
        )
    lines = ["Simulated quote comparison; these are not live exchange rates."]
    for quote in current:
        principal = format_money(
            Money(currency=quote.source_currency, amount_minor=quote.source_principal_minor)
        )
        fee = format_money(Money(currency=quote.source_currency, amount_minor=quote.fee_minor))
        total = format_money(
            Money(currency=quote.source_currency, amount_minor=quote.source_total_minor)
        )
        lines.append(
            f"{quote.id}: principal {principal} + fee {fee} = total {total}; "
            f"simulated recipient amount {format_money(destination)}. "
            f"Displayed rate (rounded): 1 IDR = {display_rate(quote.rate)} CNY. "
            f"Expires {utc_time(quote.expires_at)}; "
            f"estimated provider delivery {utc_time(quote.estimated_delivery_at)}."
        )
    cheapest = current[0].source_total_minor
    winners = ", ".join(quote.id for quote in current if quote.source_total_minor == cheapest)
    lines.append(f"Lowest quoted total for the same recipient amount: {winners}.")
    if current[-1].source_total_minor > cheapest:
        saving = format_money(
            Money(
                currency=Currency.IDR,
                amount_minor=current[-1].source_total_minor - cheapest,
            )
        )
        lines.append(f"The difference from the highest comparable quoted total is {saving}.")
    lines.append(
        "IDR is shown in whole rupiah; CNY includes two decimal places (fen). "
        "Totals include the stated simulated fees only. "
        "Provider delivery does not establish university tuition posting. "
        "Funding eligibility and authorization must be checked separately."
    )
    return "\n".join(lines)
