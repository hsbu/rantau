"""Regression tests for defects found by reviewing the demo-readiness branch."""

from datetime import timedelta

from backend.contracts.enums import PaymentState, TuitionState
from backend.contracts.models import CaseSubmission
from backend.demo.reset import reset_demo_fixture
from backend.finance.executor import prune_idempotency_keys
from backend.finance.outcomes import Executed
from backend.finance.quotes import QuoteService
from tests.finance.conftest import TENANT
from tests.finance.factories import OBLIGATION, authorize, count, proposal, scalar
from tests.finance.test_university import advance, obligation, pay, settle

DESTINATION = 2_000_000


def issue(database):
    with database.connection() as connection:
        return QuoteService().issue(connection, TENANT, DESTINATION)


def test_a_quote_close_to_expiry_is_replaced_not_reused(finance_db):
    first = issue(finance_db)
    with finance_db.connection() as connection:
        connection.execute("UPDATE fx_quotes SET expires_at = now() + interval '5 seconds'")
    second = issue(finance_db)
    assert {quote.id for quote in first}.isdisjoint({quote.id for quote in second})
    for quote in second:
        with finance_db.connection() as connection:
            now = connection.execute("SELECT now() AS now").fetchone()["now"]
        assert quote.expires_at - now > timedelta(minutes=10)


def test_a_healthy_quote_is_still_reused_inside_its_window(finance_db):
    assert [q.id for q in issue(finance_db)] == [q.id for q in issue(finance_db)]


def test_the_obligation_remembers_that_a_reconciliation_resolved(services, student):
    reset_demo_fixture(services.database, TENANT, "tuition_missing_reference")
    _, result = pay(services, student)
    assert obligation(services.database).reconciliation_resolved is False
    case = services.cases.create(
        student,
        CaseSubmission(payment_id=result.payment_id, obligation_id=OBLIGATION, evidence_ids=()),
    )
    services.cases.submit(student, case.id)
    services.review.review_submitted(TENANT)
    snapshot = obligation(services.database)
    assert snapshot.obligation.state == TuitionState.PAID and snapshot.reconciliation_resolved


def test_a_normal_payment_never_reports_a_resolved_reconciliation(services, student):
    pay(services, student)
    advance(services.database, 25)
    settle(services.database)
    assert obligation(services.database).reconciliation_resolved is False


def test_an_overpaying_receipt_is_escalated_once_instead_of_failing_the_tick(services, student):
    _, result = pay(services, student)
    with services.database.connection() as connection:
        connection.execute("UPDATE university_receipts SET received_minor = 2500000")
    advance(services.database, 25)
    assert settle(services.database) == 0
    assert settle(services.database) == 0
    assert obligation(services.database).obligation.state == TuitionState.ESCALATED
    assert count(services.database, "university_postings") == 0
    escalated = scalar(
        services.database, "SELECT count(*) FROM reconciliation_cases WHERE state = 'ESCALATED'"
    )
    assert escalated == 1 and result.transfer_state == PaymentState.DELIVERED
    assert (
        scalar(
            services.database,
            "SELECT count(*) FROM audit_events WHERE action = 'RECONCILIATION_ESCALATED'",
        )
        == 1
    )


def test_old_idempotency_keys_for_settled_payments_are_pruned_but_active_ones_kept(
    services, student
):
    alias = services.intents.create(student, proposal()).intent.id
    authorize(services, alias)
    done = services.executor.execute(student, alias, "key-old")
    assert isinstance(done, Executed)
    with services.database.connection() as connection:
        connection.execute("UPDATE idempotency_keys SET created_at = now() - interval '3 days'")
        assert prune_idempotency_keys(connection, TENANT, timedelta(days=1)) == 1
    assert count(services.database, "idempotency_keys") == 0


def test_recent_and_unsettled_idempotency_keys_are_never_pruned(services, student):
    from backend.contracts.enums import FaultMode
    from backend.finance.provider import set_fault

    with services.database.connection() as connection:
        set_fault(connection, TENANT, "mock_remit_a", FaultMode.TIMEOUT_AFTER_ACCEPT)
    alias = services.intents.create(student, proposal()).intent.id
    authorize(services, alias)
    services.executor.execute(student, alias, "key-unknown")
    with services.database.connection() as connection:
        connection.execute("UPDATE idempotency_keys SET created_at = now() - interval '3 days'")
        assert prune_idempotency_keys(connection, TENANT, timedelta(days=1)) == 0
    assert count(services.database, "idempotency_keys") == 1


def test_spending_coverage_markers_come_from_the_last_clock_reading(services, student, monkeypatch):
    import backend.finance.policy_repo as repo
    from backend.contracts.models import ActionIntent

    alias = services.intents.create(student, proposal()).intent.id
    real = repo.db_now
    readings = []

    def clock(connection):
        value = real(connection)
        readings.append(value)
        return value

    monkeypatch.setattr(repo, "db_now", clock)
    with services.database.connection() as connection:
        snapshot = repo.FinancePolicyRepository(services.authority).load_payment(
            connection,
            student,
            ActionIntent(action="EXECUTE_PAYMENT", resource_id=alias, terms_hash="x"),
        )
    local = readings[-1].astimezone(__import__("zoneinfo").ZoneInfo(snapshot.account.timezone))
    assert snapshot.spending_day == local.date() and len(readings) >= 2
