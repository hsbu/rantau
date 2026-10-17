"""Builders shared by finance tests; keep test bodies about one behaviour."""

from backend.contracts.models import IntentProposal
from backend.demo.scenarios import (
    BENEFICIARY_ALIAS,
    OBLIGATION_ALIAS,
    POLICY_VERSION,
    SPONSOR_ACCOUNT,
    STUDENT_ID,
)
from backend.finance.quotes import QuoteService
from tests.finance.conftest import TENANT

DEFAULT_QUOTE = "quote_001"


def add_obligation(database, alias: str, due_minor: int):
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO tuition_obligations (tenant_id, alias, student_id, university_id, "
            "currency, amount_due_minor, due_at, policy_alias) "
            "VALUES (%s, %s, %s, 'uni_cn_01', 'CNY', %s, now() + interval '20 days', %s)",
            (TENANT, alias, STUDENT_ID, due_minor, POLICY_VERSION),
        )
        quotes = QuoteService().issue(connection, TENANT, due_minor)
    return quotes[0].id


def proposal(
    obligation: str = OBLIGATION_ALIAS,
    quote: str = DEFAULT_QUOTE,
    account: str = SPONSOR_ACCOUNT.alias,
    beneficiary: str = BENEFICIARY_ALIAS,
) -> IntentProposal:
    return IntentProposal(
        obligation_id=obligation,
        source_account_id=account,
        beneficiary_id=beneficiary,
        quote_id=quote,
        purpose="TUITION",
    )


def authorize(services, intent_alias: str) -> None:
    """Stand in for B-03: record the owner's approval and move the intent to AUTHORIZED."""
    services.authority.approved.add(intent_alias)
    with services.database.connection() as connection:
        connection.execute(
            "UPDATE payment_intents SET state = 'AUTHORIZED' WHERE tenant_id = %s AND alias = %s",
            (TENANT, intent_alias),
        )


def scalar(database, sql: str, params: tuple = ()):
    with database.connection() as connection:
        row = connection.execute(sql, params).fetchone()
    return next(iter(row.values())) if row else None


def balance(database, account: str = SPONSOR_ACCOUNT.alias) -> int:
    return scalar(
        database,
        "SELECT balance_minor FROM funding_accounts WHERE tenant_id = %s AND alias = %s",
        (TENANT, account),
    )


def count(database, table: str) -> int:
    return scalar(database, f"SELECT count(*) FROM {table}")  # noqa: S608
