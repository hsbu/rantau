"""Tenant-scoped row access shared by commands and the policy repository.

Lock order for every financial writer: funding account, obligation, intent.
"""

from dataclasses import dataclass
from typing import Any, Literal

from backend.authz.policy_repository import PolicyConnection
from backend.contracts.enums import Currency, PaymentState, Tier
from backend.contracts.models import PaymentIntent, ScopeDenied

Row = dict[str, Any]
_SELECTORS = {
    "intent": "payment_intents",
    "account": "funding_accounts",
    "obligation": "tuition_obligations",
    "quote": "fx_quotes",
    "beneficiary": "beneficiaries",
}


@dataclass(frozen=True)
class LockedIntent:
    intent: Row
    account: Row
    obligation: Row | None


def fetch(
    connection: PolicyConnection,
    kind: Literal["intent", "account", "obligation", "quote", "beneficiary"],
    tenant_id: str,
    alias: str,
    *,
    lock: str = "",
) -> Row | None:
    return connection.execute(
        f"SELECT * FROM {_SELECTORS[kind]} WHERE tenant_id = %s AND alias = %s {lock}",  # noqa: S608
        (tenant_id, alias),
    ).fetchone()


def lock_intent(connection: PolicyConnection, tenant_id: str, alias: str) -> LockedIntent:
    """Take the documented lock order, then re-read the intent under its own lock."""
    unlocked = fetch(connection, "intent", tenant_id, alias)
    if unlocked is None:
        raise ScopeDenied("Resource unavailable")
    account = fetch(
        connection, "account", tenant_id, unlocked["source_account_alias"], lock="FOR UPDATE"
    )
    obligation = (
        fetch(connection, "obligation", tenant_id, unlocked["obligation_alias"], lock="FOR UPDATE")
        if unlocked["obligation_alias"]
        else None
    )
    intent = fetch(connection, "intent", tenant_id, alias, lock="FOR UPDATE")
    if account is None or intent is None:
        raise ScopeDenied("Resource unavailable")
    return LockedIntent(intent, account, obligation)


def intent_from_row(row: Row) -> PaymentIntent:
    return PaymentIntent(
        id=row["alias"],
        intent_id=row["alias"],
        intent_revision=row["intent_revision"],
        funding_owner_id=row["funding_owner_id"],
        source_account_id=row["source_account_alias"],
        beneficiary_id=row["beneficiary_alias"],
        beneficiary_fingerprint=row["beneficiary_fingerprint"],
        purpose=row["purpose"],
        obligation_id=row["obligation_alias"],
        source_currency=Currency(row["source_currency"]),
        destination_currency=Currency(row["destination_currency"]),
        source_total_minor=row["source_total_minor"],
        destination_amount_minor=row["destination_amount_minor"],
        quote_id=row["quote_alias"],
        quote_expiry=row["quote_expiry"],
        policy_version=row["policy_version"],
        terms_hash=row["terms_hash"],
        requested_by=row["requested_by"],
        tier=Tier(row["tier"]),
        state=PaymentState(row["state"]),
    )


def may_view(actor_id: str, intent: Row) -> bool:
    return actor_id in {intent["requested_by"], intent["funding_owner_id"]}
