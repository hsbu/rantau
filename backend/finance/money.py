"""Single home for money arithmetic: integer minor units, exact decimal rates, no floats."""

import re
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from backend.contracts.enums import CURRENCY_SCALE, Currency

MAX_MINOR = 9_007_199_254_740_991
BPS_DENOMINATOR = 10_000
# Mirrors the FxQuote.rate contract so a rate accepted here is always a valid quote rate.
_RATE_PATTERN = re.compile(r"^(?:0|[1-9]\d{0,8})(?:\.\d{1,28})?$")
# One principal step can skip a destination minor unit only at extreme rates.
_PRICING_SEARCH_WINDOW = 2


def to_minor(value: str | Decimal | int, currency: Currency) -> int:
    """Parse a major-unit amount exactly; reject floats, extra precision and negatives."""
    if isinstance(value, float | bool):
        raise TypeError("Binary floats are not allowed for money")
    amount = _finite_decimal(value)
    scaled = amount.scaleb(CURRENCY_SCALE[currency])
    if scaled != scaled.to_integral_value() or scaled > MAX_MINOR:
        raise ValueError("Amount has excess precision or exceeds the safe integer bound")
    return int(scaled)


def convert_minor(source_minor: int, rate: str, source: Currency, destination: Currency) -> int:
    """Convert with the same HALF_UP rounding the FxQuote contract enforces."""
    exact = Fraction(source_minor) * _minor_per_minor(rate, source, destination)
    return _round_half_up(exact)


def price_for_destination(
    destination_minor: int, rate: str, source: Currency, destination: Currency
) -> int:
    """Principal nearest destination/rate whose conversion is exactly destination_minor."""
    nearest = _round_half_up(
        Fraction(destination_minor) / _minor_per_minor(rate, source, destination)
    )
    for principal in _nearest_first(nearest):
        if convert_minor(principal, rate, source, destination) == destination_minor:
            return principal
    raise ValueError("Destination amount is not exactly reachable at this rate")


def fee_minor(principal_minor: int, *, bps: int, floor: int) -> int:
    """Integer basis-point fee rounded half up, never below the floor."""
    proportional = _round_half_up(Fraction(principal_minor * bps, BPS_DENOMINATOR))
    return max(floor, proportional)


def _finite_decimal(value: str | Decimal | int) -> Decimal:
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError("Amount is not a decimal number") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError("Amount must be a finite non-negative number")
    return amount


def _minor_per_minor(rate: str, source: Currency, destination: Currency) -> Fraction:
    exponent = CURRENCY_SCALE[destination] - CURRENCY_SCALE[source]
    return Fraction(_parse_rate(rate)) * Fraction(10) ** exponent


def _parse_rate(rate: str) -> Decimal:
    if not _RATE_PATTERN.fullmatch(rate) or Decimal(rate) <= 0:
        raise ValueError("Rate must be an exact positive decimal string")
    return Decimal(rate)


def _round_half_up(value: Fraction) -> int:
    return (value.numerator * 2 + value.denominator) // (value.denominator * 2)


def _nearest_first(center: int) -> list[int]:
    candidates = range(max(1, center - _PRICING_SEARCH_WINDOW), center + _PRICING_SEARCH_WINDOW + 1)
    return sorted(candidates, key=lambda value: abs(value - center))
