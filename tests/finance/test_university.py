from backend.contracts.enums import FaultMode, PaymentState, ReasonCode, TuitionState
from backend.demo.reset import reset_demo_fixture
from backend.finance.outcomes import Created, Executed, Refused
from backend.finance.provider import set_fault
from backend.finance.quotes import QuoteService
from backend.finance.records import fetch
from backend.finance.simclock import advance_sim_clock, sim_now
from backend.university.ledger import settle_due
from backend.university.obligations import read_obligation
from tests.finance.conftest import TENANT
from tests.finance.factories import OBLIGATION, authorize, count, proposal, scalar

DUE = 2_000_000
SHORT = 150_000


def pay(services, student, key="key-1", **kwargs):
    alias = services.intents.create(student, proposal(**kwargs)).intent.id
    authorize(services, alias)
    return alias, services.executor.execute(student, alias, key)


def obligation(database):
    with database.connection() as connection:
        row = fetch(connection, "obligation", TENANT, OBLIGATION)
        return read_obligation(connection, TENANT, row, sim_now(connection, TENANT))


def advance(database, hours):
    with database.connection() as connection:
        advance_sim_clock(connection, TENANT, int(hours * 3600))


def settle(database):
    with database.connection() as connection:
        return settle_due(connection, TENANT)


def test_delivered_funds_are_not_tuition_paid(services, student):
    _, result = pay(services, student)
    assert result.transfer_state == PaymentState.DELIVERED
    snapshot = obligation(services.database)
    assert snapshot.obligation.state == TuitionState.AWAITING_POSTING
    assert snapshot.obligation.posted_minor == 0 and snapshot.obligation.balance_minor == DUE


def test_an_open_window_blocks_a_repeat_payment_without_calling_it_a_failure(services, student):
    pay(services, student)
    second = services.intents.create(student, proposal())
    assert (
        isinstance(second, Created)
        and second.decision.reason_code == ReasonCode.POSTING_WINDOW_ACTIVE
    )
    authorize(services, second.intent.id)
    assert isinstance(services.executor.execute(student, second.intent.id, "key-2"), Refused)
    assert count(services.database, "transfers") == 1


def test_posting_happens_once_when_simulated_time_arrives(services, student):
    pay(services, student)
    assert settle(services.database) == 0
    advance(services.database, 25)
    assert settle(services.database) == 1
    assert settle(services.database) == 0
    snapshot = obligation(services.database)
    assert snapshot.obligation.state == TuitionState.PAID
    assert scalar(services.database, "SELECT count(*) FROM university_postings") == 1
    assert scalar(services.database, "SELECT blocks_obligation FROM transfers") is False


def test_a_posting_that_misses_the_window_becomes_an_exception_not_a_payment_claim(
    services, student
):
    pay(services, student)
    with services.database.connection() as connection:
        connection.execute(
            "UPDATE university_receipts SET post_after = window_deadline + interval '1 hour'"
        )
    advance(services.database, 48.5)
    assert obligation(services.database).obligation.state == TuitionState.EXCEPTION
    held = services.intents.create(student, proposal())
    assert held.decision.reason_code == ReasonCode.RECONCILIATION_NEEDS_INFO


def short_payment_posted(services, student):
    with services.database.connection() as connection:
        set_fault(connection, TENANT, "mock_remit_a", FaultMode.SHORT_PAYMENT)
    pay(services, student)
    advance(services.database, 25)
    settle(services.database)


def topup_proposal(services):
    with services.database.connection() as connection:
        quotes = QuoteService().issue(connection, TENANT, SHORT)
    return proposal(quote=quotes[0].id)


def test_a_short_payment_leaves_an_exact_integer_shortfall(services, student):
    short_payment_posted(services, student)
    snapshot = obligation(services.database)
    assert snapshot.obligation.state == TuitionState.PARTIALLY_POSTED
    assert (snapshot.obligation.posted_minor, snapshot.obligation.balance_minor) == (
        DUE - SHORT,
        SHORT,
    )


def test_a_topup_is_refused_when_the_synthetic_policy_forbids_it(services, student):
    short_payment_posted(services, student)
    outcome = services.intents.create(student, topup_proposal(services))
    assert isinstance(outcome, Refused) and outcome.reason_code == ReasonCode.TOPUP_NOT_PERMITTED
    assert count(services.database, "payment_intents") == 1
    assert count(services.database, "transfers") == 1


def test_a_permitted_topup_needs_new_authorization_and_pays_only_the_remainder(services, student):
    reset_demo_fixture(services.database, TENANT, "shortfall_topup_on")
    short_payment_posted(services, student)
    created = services.intents.create(student, topup_proposal(services))
    assert isinstance(created, Created) and created.intent.destination_amount_minor == SHORT
    assert count(services.database, "transfers") == 1
    unapproved = services.executor.execute(student, created.intent.id, "key-topup")
    assert isinstance(unapproved, Refused)
    authorize(services, created.intent.id)
    result = services.executor.execute(student, created.intent.id, "key-topup")
    assert isinstance(result, Executed) and count(services.database, "transfers") == 2
    advance(services.database, 25)
    settle(services.database)
    assert obligation(services.database).obligation.state == TuitionState.PAID
