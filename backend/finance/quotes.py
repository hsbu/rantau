"""Fictional remittance routes and persisted, expiring quotes (always simulated)."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from backend.authz.policy_repository import PolicyConnection
from backend.contracts.enums import Currency
from backend.contracts.models import FxQuote
from backend.finance.clock import db_now
from backend.finance.money import fee_minor, price_for_destination

DEFAULT_QUOTE_TTL_SECONDS = 900
CNY_PER_IDR_RATE = "0.0004347826086956521739130435"


@dataclass(frozen=True)
class Route:
    provider: str
    rate: str
    fee_bps: int
    fee_floor_minor: int
    delivery: timedelta


ROUTES = (
    Route("mock_remit_a", CNY_PER_IDR_RATE, 5, 25_000, timedelta(days=1)),
    Route("mock_remit_b", CNY_PER_IDR_RATE, 10, 50_000, timedelta(hours=2)),
)


class QuoteService:
    def __init__(
        self,
        routes: tuple[Route, ...] = ROUTES,
        ttl_seconds: int = DEFAULT_QUOTE_TTL_SECONDS,
    ) -> None:
        self.routes = routes
        self.ttl = timedelta(seconds=ttl_seconds)

    def issue(
        self,
        connection: PolicyConnection,
        tenant_id: str,
        destination_minor: int,
        aliases: Mapping[str, str] | None = None,
    ) -> tuple[FxQuote, ...]:
        """Persist one quote per route; repeating a request inside its TTL bucket is idempotent."""
        now = db_now(connection)
        quotes = [
            self._issue_route(
                connection,
                tenant_id,
                route,
                destination_minor,
                now,
                (aliases or {}).get(route.provider),
            )
            for route in self.routes
        ]
        return tuple(sorted(quotes, key=_comparison_key))

    def _issue_route(
        self,
        connection: PolicyConnection,
        tenant_id: str,
        route: Route,
        destination_minor: int,
        now: datetime,
        alias: str | None,
    ) -> FxQuote:
        principal = price_for_destination(destination_minor, route.rate, Currency.IDR, Currency.CNY)
        fee = fee_minor(principal, bps=route.fee_bps, floor=route.fee_floor_minor)
        digest = self._request_digest(route, destination_minor, now)
        connection.execute(
            "INSERT INTO fx_quotes (tenant_id, alias, provider, source_currency, "
            "destination_currency, source_principal_minor, fee_minor, source_total_minor, "
            "destination_amount_minor, rate, expires_at, estimated_delivery_at, request_digest) "
            "VALUES (%s, COALESCE(%s, 'quote_' || substr(md5(random()::text), 1, 12)), %s, "
            "'IDR', 'CNY', %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (tenant_id, provider, request_digest) DO NOTHING",
            (
                tenant_id,
                alias,
                route.provider,
                principal,
                fee,
                principal + fee,
                destination_minor,
                route.rate,
                now + self.ttl,
                now + route.delivery,
                digest,
            ),
        )
        row = connection.execute(
            "SELECT * FROM fx_quotes WHERE tenant_id = %s AND provider = %s "
            "AND request_digest = %s",
            (tenant_id, route.provider, digest),
        ).fetchone()
        assert row is not None
        return quote_from_row(row)

    def _request_digest(self, route: Route, destination_minor: int, now: datetime) -> str:
        bucket = int(now.timestamp() // self.ttl.total_seconds())
        material = f"{route.provider}|{destination_minor}|{bucket}"
        return hashlib.sha256(material.encode()).hexdigest()


def quote_from_row(row: dict[str, Any]) -> FxQuote:
    return FxQuote(
        id=row["alias"],
        provider=row["provider"],
        source_currency=Currency(row["source_currency"]),
        destination_currency=Currency(row["destination_currency"]),
        source_principal_minor=row["source_principal_minor"],
        fee_minor=row["fee_minor"],
        source_total_minor=row["source_total_minor"],
        destination_amount_minor=row["destination_amount_minor"],
        rate=row["rate"],
        expires_at=row["expires_at"],
        estimated_delivery_at=row["estimated_delivery_at"],
    )


def _comparison_key(quote: FxQuote) -> tuple[int, datetime, str]:
    return (quote.source_total_minor, quote.estimated_delivery_at, quote.id)
