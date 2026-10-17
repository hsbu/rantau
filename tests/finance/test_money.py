from decimal import Decimal

import pytest

from backend.contracts.enums import Currency
from backend.contracts.models import FxQuote
from backend.finance.money import (
    MAX_MINOR,
    convert_minor,
    fee_minor,
    price_for_destination,
    to_minor,
)
from tests.fixtures.data import QUOTE

RATE = QUOTE.rate


def test_convert_matches_the_contract_quote_fixture():
    converted = convert_minor(QUOTE.source_principal_minor, RATE, Currency.IDR, Currency.CNY)
    assert converted == QUOTE.destination_amount_minor


def test_convert_rounds_half_up_in_destination_minor_units():
    # 1 IDR at 0.005 CNY = 0.5 fen -> rounds up to 1 fen; 0.4 fen rounds down.
    assert convert_minor(1, "0.005", Currency.IDR, Currency.CNY) == 1
    assert convert_minor(1, "0.004", Currency.IDR, Currency.CNY) == 0


def test_pricing_returns_the_principal_the_contract_validator_accepts():
    principal = price_for_destination(2_000_000, RATE, Currency.IDR, Currency.CNY)
    assert principal == 46_000_000
    FxQuote(
        id="quote_price_check",
        provider="mock_remit_a",
        source_currency=Currency.IDR,
        destination_currency=Currency.CNY,
        source_principal_minor=principal,
        fee_minor=1,
        source_total_minor=principal + 1,
        destination_amount_minor=2_000_000,
        rate=RATE,
        expires_at=QUOTE.expires_at,
        estimated_delivery_at=QUOTE.estimated_delivery_at,
    )


@pytest.mark.parametrize("destination", [1, 99, 100, 1_234_567, 2_000_000, 999_999_999])
def test_pricing_always_converts_back_to_the_exact_destination(destination):
    principal = price_for_destination(destination, RATE, Currency.IDR, Currency.CNY)
    assert convert_minor(principal, RATE, Currency.IDR, Currency.CNY) == destination


def test_pricing_rejects_a_rate_that_cannot_reach_the_destination_exactly():
    # 1 IDR = 5 CNY: every principal step jumps 500 fen, so 1 fen is unreachable.
    with pytest.raises(ValueError):
        price_for_destination(1, "5", Currency.IDR, Currency.CNY)


@pytest.mark.parametrize("rate", ["0", "-1", "abc", "1e3", "0.00043478261.5"])
def test_invalid_rates_are_rejected(rate):
    with pytest.raises(ValueError):
        convert_minor(1_000, rate, Currency.IDR, Currency.CNY)


def test_fee_is_integer_basis_points_with_a_floor():
    assert fee_minor(46_000_000, bps=5, floor=25_000) == 25_000
    assert fee_minor(46_000_000, bps=100, floor=25_000) == 460_000
    assert fee_minor(1, bps=1, floor=0) == 0


def test_fee_rounds_half_up_not_by_float():
    assert fee_minor(50_000, bps=1, floor=0) == 5
    assert fee_minor(5_000, bps=1, floor=0) == 1  # 0.5 -> 1


@pytest.mark.parametrize(
    ("value", "currency", "expected"),
    [
        ("20000", Currency.CNY, 2_000_000),
        ("20000.00", Currency.CNY, 2_000_000),
        ("0.01", Currency.CNY, 1),
        ("46025000", Currency.IDR, 46_025_000),
    ],
)
def test_to_minor_is_exact(value, currency, expected):
    assert to_minor(value, currency) == expected


@pytest.mark.parametrize(
    ("value", "currency"),
    [("0.001", Currency.CNY), ("1.5", Currency.IDR), ("-1", Currency.CNY), ("nan", Currency.CNY)],
)
def test_to_minor_rejects_extra_precision_negatives_and_non_numbers(value, currency):
    with pytest.raises(ValueError):
        to_minor(value, currency)


def test_to_minor_rejects_binary_floats():
    with pytest.raises(TypeError):
        to_minor(0.1, Currency.CNY)  # type: ignore[arg-type]


def test_to_minor_rejects_amounts_beyond_the_javascript_safe_integer():
    assert to_minor(str(MAX_MINOR), Currency.IDR) == MAX_MINOR
    with pytest.raises(ValueError):
        to_minor(str(MAX_MINOR + 1), Currency.IDR)


def test_decimal_input_is_accepted():
    assert to_minor(Decimal("12.34"), Currency.CNY) == 1234
