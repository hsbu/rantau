"""Deterministic display of validated synthetic quotes; never payment authority."""

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

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


def display_time(value: datetime) -> str:
    utc_time(value)
    return value.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%d %b %Y, %H:%M China time")


def route_label(quote: FxQuote, index: int = 1) -> str:
    return {"mock_remit_a": "Standard route", "mock_remit_b": "Faster route"}.get(
        quote.provider, f"Route {index}"
    )


def explain_tuition_record(obligation: TuitionObligation) -> str:
    expected = format_money(
        Money(currency=obligation.currency, amount_minor=obligation.amount_due_minor)
    )
    posted = format_money(Money(currency=obligation.currency, amount_minor=obligation.posted_minor))
    remaining = format_money(
        Money(currency=obligation.currency, amount_minor=obligation.balance_minor)
    )
    return (
        f"**Tuition remaining: {remaining}**\n\n"
        f"- Amount due: {expected}\n"
        f"- University credited: {posted}\n"
        f"- Due date: {display_time(obligation.due_at)}"
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
            "I couldn’t find a current quote for this amount. Refresh the quote before proceeding."
        )
    lines = ["**Available payment routes**"]
    for index, quote in enumerate(current, 1):
        principal = format_money(
            Money(currency=quote.source_currency, amount_minor=quote.source_principal_minor)
        )
        fee = format_money(Money(currency=quote.source_currency, amount_minor=quote.fee_minor))
        total = format_money(
            Money(currency=quote.source_currency, amount_minor=quote.source_total_minor)
        )
        lines.append(
            f"{index}. **{route_label(quote, index)} — {total} total**\n"
            f"Transfer amount: {principal}; fee: {fee}.\n"
            f"University receives: {format_money(destination)}.\n"
            f"Rate (rounded): 1 IDR = {display_rate(quote.rate)} CNY.\n"
            f"Quote expires: {display_time(quote.expires_at)}.\n"
            f"Estimated arrival: {display_time(quote.estimated_delivery_at)}."
        )
    winners = [
        str(i)
        for i, q in enumerate(current, 1)
        if q.source_total_minor == current[0].source_total_minor
    ]
    lines.append(
        "Lowest total for the same recipient amount: "
        + ", ".join(f"route {i}" for i in winners)
        + "."
    )
    if current[-1].source_total_minor > current[0].source_total_minor:
        saving = format_money(
            Money(
                currency=Currency.IDR,
                amount_minor=current[-1].source_total_minor - current[0].source_total_minor,
            )
        )
        lines.append(f"The difference from the highest quoted total is {saving}.")
    lines.append(
        "Arrival estimates describe provider delivery. "
        "Tuition is settled only when the university credits it."
    )
    return "\n\n".join(lines)


def explain_selected_quote(quote: FxQuote, index: int) -> str:
    total = format_money(
        Money(currency=quote.source_currency, amount_minor=quote.source_total_minor)
    )
    fee = format_money(Money(currency=quote.source_currency, amount_minor=quote.fee_minor))
    destination = format_money(
        Money(currency=quote.destination_currency, amount_minor=quote.destination_amount_minor)
    )
    return (
        f"**Selected: {route_label(quote, index)}**\n\n"
        f"- Total debit: **{total}** (includes {fee} fee)\n"
        f"- University receives: {destination}\n"
        f"- Rate (rounded): 1 IDR = {display_rate(quote.rate)} CNY\n"
        f"- Estimated arrival: {display_time(quote.estimated_delivery_at)}\n"
        f"- Quote expires: {display_time(quote.expires_at)}"
    )
