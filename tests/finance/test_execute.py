import pytest

from backend.contracts.enums import Decision, PaymentState, ReasonCode
from backend.contracts.models import ScopeDenied
from backend.demo.reset import reset_demo_fixture
from backend.finance.executor import IdempotencyKeyReused
from backend.finance.outcomes import Executed, Refused
from tests.finance.conftest import PASSWORD, TENANT
from tests.finance.factories import (
    add_obligation,
    authorize,
    balance,
    count,
    proposal,
    scalar,
)

TOTAL = 46_025_000
OPENING = 150_000_000


def approved_intent(services, student, approve=True, **kwargs):
    alias = services.intents.create(student, proposal(**kwargs)).intent.id
    if approve:
        authorize(services, alias)
    return alias


def ledger_totals(database):
    return scalar(
        database,
        "SELECT (SELECT COALESCE(sum(amount_minor), 0) FROM ledger_entries "
        "WHERE direction = 'DEBIT') - (SELECT COALESCE(sum(amount_minor), 0) "
        "FROM ledger_entries WHERE direction = 'CREDIT')",
    )


def test_approved_payment_debits_once_and_records_every_effect(services, student):
    alias = approved_intent(services, student)
    result = services.executor.execute(student, alias, "key-001")
    assert isinstance(result, Executed)
    assert result.transfer_state == PaymentState.DELIVERED and not result.replayed
    db = services.database
    assert balance(db) == OPENING - TOTAL
    assert count(db, "transfers") == 1 and count(db, "spend_entries") == 1
    assert count(db, "ledger_entries") == 3 and ledger_totals(db) == 0
    assert scalar(db, "SELECT state FROM payment_intents") == "DELIVERED"
    assert scalar(db, "SELECT count(*) FROM audit_events WHERE action = 'PAYMENT_DEBITED'") == 1
    assert scalar(db, "SELECT count(*) FROM policy_decisions WHERE decision = 'ALLOW'") == 1


def test_retrying_the_same_key_returns_the_same_result_without_a_second_debit(services, student):
    alias = approved_intent(services, student)
    first = services.executor.execute(student, alias, "key-retry")
    second = services.executor.execute(student, alias, "key-retry")
    assert isinstance(second, Executed) and second.replayed
    assert (second.payment_id, second.audit_event_id) == (first.payment_id, first.audit_event_id)
    assert balance(services.database) == OPENING - TOTAL
    assert count(services.database, "transfers") == 1


def test_reusing_a_key_for_another_intent_is_rejected(services, student):
    first = approved_intent(services, student)
    other_quote = add_obligation(services.database, "obl_other", 1_000_000)
    second = approved_intent(services, student, obligation="obl_other", quote=other_quote)
    services.executor.execute(student, first, "key-shared")
    with pytest.raises(IdempotencyKeyReused):
        services.executor.execute(student, second, "key-shared")
    assert count(services.database, "transfers") == 1


def test_a_new_key_cannot_pay_the_same_intent_twice(services, student):
    alias = approved_intent(services, student)
    services.executor.execute(student, alias, "key-one")
    again = services.executor.execute(student, alias, "key-two")
    assert isinstance(again, Refused)
    assert again.reason_code == ReasonCode.PAYMENT_ALREADY_SUBMITTED
    assert balance(services.database) == OPENING - TOTAL


def test_missing_approval_moves_no_money_but_leaves_audit(services, student):
    alias = approved_intent(services, student, approve=False)
    result = services.executor.execute(student, alias, "key-no-approval")
    assert isinstance(result, Refused)
    assert result.decision and result.decision.decision == Decision.REQUIRE_APPROVAL
    assert result.reason_code == ReasonCode.FUNDING_OWNER_APPROVAL_REQUIRED
    assert balance(services.database) == OPENING
    assert count(services.database, "transfers") == 0
    assert count(services.database, "idempotency_keys") == 0
    assert (
        scalar(
            services.database,
            "SELECT count(*) FROM audit_events WHERE action = 'EXECUTION_REFUSED'",
        )
        == 1
    )


def test_the_same_key_may_proceed_after_approval_arrives(services, student):
    alias = approved_intent(services, student, approve=False)
    assert isinstance(services.executor.execute(student, alias, "key-wait"), Refused)
    authorize(services, alias)
    assert isinstance(services.executor.execute(student, alias, "key-wait"), Executed)


def test_a_client_claiming_different_terms_is_refused(services, student):
    alias = approved_intent(services, student)
    result = services.executor.execute(student, alias, "key-claim", claimed_terms_hash="0" * 64)
    assert isinstance(result, Refused)
    assert result.reason_code == ReasonCode.APPROVAL_TERMS_MISMATCH
    assert balance(services.database) == OPENING


def test_an_expired_quote_blocks_execution(services, student):
    alias = approved_intent(services, student)
    with services.database.connection() as connection:
        connection.execute("UPDATE fx_quotes SET expires_at = now() - interval '1 second'")
    result = services.executor.execute(student, alias, "key-expired")
    assert isinstance(result, Refused) and result.reason_code == ReasonCode.QUOTE_EXPIRED
    assert balance(services.database) == OPENING


def test_insufficient_funds_blocks_execution(services, student):
    alias = approved_intent(services, student)
    with services.database.connection() as connection:
        connection.execute(
            "UPDATE funding_accounts SET balance_minor = 1000 WHERE alias = 'acct_idr_01'"
        )
    result = services.executor.execute(student, alias, "key-poor")
    assert isinstance(result, Refused) and result.reason_code == ReasonCode.INSUFFICIENT_FUNDS
    assert balance(services.database) == 1000


def test_a_security_hold_blocks_execution(services, student):
    alias = approved_intent(services, student)
    services.authority.held = True
    result = services.executor.execute(student, alias, "key-held")
    assert isinstance(result, Refused) and result.reason_code == ReasonCode.SECURITY_HOLD
    assert count(services.database, "transfers") == 0


def test_a_second_intent_for_an_unresolved_obligation_is_held(services, student):
    first = approved_intent(services, student)
    services.executor.execute(student, first, "key-first")
    second = services.intents.create(student, proposal())
    assert second.decision.reason_code == ReasonCode.POSTING_WINDOW_ACTIVE
    assert count(services.database, "transfers") == 1


def test_an_unrelated_student_cannot_execute_the_intent(services, student, password_hash):
    alias = approved_intent(services, student)
    with services.database.connection() as connection:
        connection.execute(
            "INSERT INTO actors (tenant_id, actor_id, role, scopes) VALUES (%s, 'stu_002', "
            "'STUDENT', ARRAY['student:read','payment:propose','payment:execute'])",
            (TENANT,),
        )
        connection.execute(
            "INSERT INTO auth_credentials (tenant_id, actor_id, username, password_hash) "
            "VALUES (%s, 'stu_002', 'stranger', %s)",
            (TENANT, password_hash),
        )
    stranger = services.auth.login("stranger", PASSWORD, "finance-tests").actor
    with pytest.raises(ScopeDenied):
        services.executor.execute(stranger, alias, "key-stranger")
    assert count(services.database, "transfers") == 0


def test_logs_and_audit_never_contain_account_numbers_or_keys(services, student, caplog):
    alias = approved_intent(services, student)
    services.executor.execute(student, alias, "key-secret-12345")
    with services.database.connection() as connection:
        stored = repr(connection.execute("SELECT * FROM audit_events").fetchall())
    for secret in ("key-secret-12345", "synthetic-beneficiary-fingerprint", "•••• "):
        assert secret not in stored and secret not in caplog.text
    assert TENANT in stored


def test_a_student_pays_from_their_own_account_without_the_sponsor(services, student):
    alias = approved_intent(services, student, account="acct_idr_stu_01")
    result = services.executor.execute(student, alias, "key-self")
    assert isinstance(result, Executed)
    assert balance(services.database, "acct_idr_stu_01") == 60_000_000 - TOTAL
    assert balance(services.database) == OPENING
    owner = scalar(services.database, "SELECT funding_owner_id FROM payment_intents")
    assert owner == "stu_001"


def test_a_forged_unverified_payee_is_held_and_can_never_be_debited(services, student):
    reset_demo_fixture(services.database, TENANT, "forged_beneficiary")
    created = services.intents.create(student, proposal(beneficiary="benef_unverified_01"))
    assert created.intent.state == PaymentState.ON_HOLD
    assert created.decision.reason_code == ReasonCode.UNKNOWN_BENEFICIARY
    authorize(services, created.intent.id)
    result = services.executor.execute(student, created.intent.id, "key-forged")
    assert isinstance(result, Refused)
    assert result.decision and result.decision.decision == Decision.HOLD
    assert count(services.database, "transfers") == 0 and balance(services.database) == OPENING
