from datetime import timedelta

from backend.contracts.enums import Currency
from backend.finance.quotes import ROUTES, QuoteService
from tests.finance.conftest import TENANT

DESTINATION = 2_000_000


def issue(database, **kwargs):
    with database.connection() as connection:
        return QuoteService(**kwargs).issue(connection, TENANT, DESTINATION)


def test_two_fictional_routes_are_compared_by_total_landed_cost(finance_db):
    cheaper, dearer = issue(finance_db)
    assert (cheaper.provider, dearer.provider) == ("mock_remit_a", "mock_remit_b")
    assert (cheaper.source_total_minor, dearer.source_total_minor) == (46_025_000, 46_050_000)
    assert cheaper.source_total_minor == cheaper.source_principal_minor + cheaper.fee_minor


def test_every_quote_delivers_the_exact_destination_amount_in_integers(finance_db):
    for quote in issue(finance_db):
        assert quote.destination_amount_minor == DESTINATION
        assert (quote.source_currency, quote.destination_currency) == (Currency.IDR, Currency.CNY)
        assert quote.synthetic is True


def test_the_faster_route_is_available_for_a_speed_preference(finance_db):
    quotes = issue(finance_db)
    fastest = min(quotes, key=lambda quote: quote.estimated_delivery_at)
    assert fastest.provider == "mock_remit_b"
    assert len(quotes) == len(ROUTES)


def test_quotes_expire_after_the_configured_window(finance_db):
    quote = issue(finance_db, ttl_seconds=600)[0]
    assert timedelta(minutes=9) < quote.expires_at - _now(finance_db) <= timedelta(minutes=10)


def test_repeating_a_request_inside_the_window_reuses_the_stored_quotes(finance_db):
    first = issue(finance_db)
    second = issue(finance_db)
    assert [quote.id for quote in first] == [quote.id for quote in second]


def _now(database):
    with database.connection() as connection:
        return connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
