import pytest

from backend.contracts.enums import FaultMode, PaymentState, ReasonCode
from backend.contracts.models import ServiceUnavailable
from backend.finance.outcomes import Created, Executed, Refused
from backend.finance.provider import (
    EvidenceKind,
    ProviderEvidence,
    SimulatedProvider,
    SubmitRequest,
    set_fault,
)
from backend.finance.simclock import advance_sim_clock
from tests.finance.conftest import TENANT
from tests.finance.factories import authorize, balance, count, proposal, scalar

OPENING = 150_000_000
TOTAL = 46_025_000


def with_fault(database, mode, provider="mock_remit_a"):
    with database.connection() as connection:
        set_fault(connection, TENANT, provider, mode)


def pay(services, student, key="key-1"):
    alias = services.intents.create(student, proposal()).intent.id
    authorize(services, alias)
    return alias, services.executor.execute(student, alias, key)


def transfer_row(database):
    with database.connection() as connection:
        return connection.execute("SELECT * FROM transfers").fetchone()


def ledger_net(database):
    return scalar(
        database,
        "SELECT COALESCE(sum(CASE direction WHEN 'DEBIT' THEN amount_minor "
        "ELSE -amount_minor END), 0) FROM ledger_entries",
    )


def test_a_lost_response_leaves_the_outcome_unknown_and_blocks_new_debits(services, student):
    with_fault(services.database, FaultMode.TIMEOUT_AFTER_ACCEPT)
    alias, result = pay(services, student)
    assert isinstance(result, Executed) and result.transfer_state == PaymentState.OUTCOME_UNKNOWN
    assert scalar(services.database, "SELECT state FROM payment_intents") == "OUTCOME_UNKNOWN"
    again = services.executor.execute(student, alias, "key-other")
    assert isinstance(again, Refused) and again.reason_code == ReasonCode.PROVIDER_OUTCOME_UNKNOWN
    second = services.intents.create(student, proposal())
    assert isinstance(second, Created) and second.intent.state == PaymentState.ON_HOLD
    authorize(services, second.intent.id)
    blocked = services.executor.execute(student, second.intent.id, "key-new-intent")
    assert isinstance(blocked, Refused)
    assert (
        balance(services.database) == OPENING - TOTAL and count(services.database, "transfers") == 1
    )


def test_polling_the_same_reference_resolves_to_delivered_without_a_second_debit(services, student):
    with_fault(services.database, FaultMode.TIMEOUT_AFTER_ACCEPT)
    alias, first = pay(services, student, "key-poll")
    state = services.transfers.settle(TENANT, first.payment_id)
    assert state == PaymentState.DELIVERED
    replay = services.executor.execute(student, alias, "key-poll")
    assert replay.replayed and replay.transfer_state == PaymentState.DELIVERED
    assert (
        balance(services.database) == OPENING - TOTAL and count(services.database, "transfers") == 1
    )
    assert count(services.database, "university_receipts") == 1


def test_authoritative_no_debit_fails_the_payment_and_restores_the_money(services, student):
    with_fault(services.database, FaultMode.TIMEOUT_BEFORE_ACCEPT)
    alias, first = pay(services, student, "key-lost")
    assert first.transfer_state == PaymentState.OUTCOME_UNKNOWN
    assert services.transfers.settle(TENANT, first.payment_id) == PaymentState.FAILED
    db = services.database
    assert balance(db) == OPENING and ledger_net(db) == 0
    assert scalar(db, "SELECT state FROM spend_entries") == "RELEASED"
    assert scalar(db, "SELECT state FROM payment_intents") == "FAILED"
    assert scalar(db, "SELECT blocks_obligation FROM transfers") is False
    assert count(db, "ledger_entries") == 6


def test_an_unavailable_provider_fails_cleanly_with_zero_net_debit(services, student):
    with_fault(services.database, FaultMode.UNAVAILABLE)
    _, result = pay(services, student)
    assert result.transfer_state == PaymentState.FAILED
    assert balance(services.database) == OPENING and ledger_net(services.database) == 0


def test_silence_alone_never_proves_that_no_money_moved(finance_db):
    provider = SimulatedProvider(finance_db)
    assert provider.status(TENANT, "sim_ref_never_seen").kind == EvidenceKind.UNKNOWN_REFERENCE
    assert not ProviderEvidence(EvidenceKind.UNKNOWN_REFERENCE).authoritative
    assert not ProviderEvidence(EvidenceKind.NO_RESPONSE).authoritative
    assert ProviderEvidence(EvidenceKind.REJECTED_NO_DEBIT).authoritative


def test_the_provider_ignores_a_repeated_submit_of_the_same_reference(seeded):
    provider = SimulatedProvider(seeded)
    request = SubmitRequest(TENANT, "mock_remit_a", "sim_ref_x", 1_000, 100, "stu_001")
    assert provider.submit(request) == provider.submit(request)
    assert scalar(seeded, "SELECT count(*) FROM sim_provider_transfers") == 1


def test_a_crash_before_the_provider_call_is_resumed_by_retrying_the_same_key(
    services, student, monkeypatch
):
    alias = services.intents.create(student, proposal()).intent.id
    authorize(services, alias)

    def crash(request):
        raise ServiceUnavailable("simulated crash before the provider call")

    monkeypatch.setattr(services.transfers.provider, "submit", crash)
    with pytest.raises(ServiceUnavailable):
        services.executor.execute(student, alias, "key-crash")
    stranded = transfer_row(services.database)
    assert stranded["state"] == "PROCESSING" and stranded["provider_submitted_at"] is None
    monkeypatch.undo()
    resumed = services.executor.execute(student, alias, "key-crash")
    assert resumed.replayed and resumed.transfer_state == PaymentState.DELIVERED
    assert count(services.database, "transfers") == 1
    assert balance(services.database) == OPENING - TOTAL


def test_a_delayed_delivery_stays_processing_until_simulated_time_passes(services, student):
    with_fault(services.database, FaultMode.DELAYED_DELIVERY)
    _, result = pay(services, student)
    assert result.transfer_state == PaymentState.PROCESSING
    with services.database.connection() as connection:
        advance_sim_clock(connection, TENANT, 7 * 3600)
    assert services.transfers.settle(TENANT, result.payment_id) == PaymentState.DELIVERED


def test_an_unknown_outcome_cannot_be_cancelled(services, student):
    from backend.finance.states import InvalidTransition

    with_fault(services.database, FaultMode.TIMEOUT_AFTER_ACCEPT)
    alias, _ = pay(services, student)
    with pytest.raises(InvalidTransition):
        services.intents.cancel(student, alias)
