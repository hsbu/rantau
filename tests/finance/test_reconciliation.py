from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.contracts.enums import CaseState, FaultMode, PaymentState, ReasonCode, TuitionState
from backend.contracts.models import CaseSubmission, ScopeDenied
from backend.demo.reset import reset_demo_fixture
from backend.finance.outcomes import Created, Refused
from backend.finance.provider import set_fault
from backend.university.rules import ReviewReason
from tests.finance.conftest import TENANT
from tests.finance.factories import OBLIGATION, authorize, balance, count, proposal, scalar
from tests.finance.test_university import obligation, pay

OPENING = 150_000_000
TOTAL = 46_025_000


def delivered_without_reference(services, student):
    reset_demo_fixture(services.database, TENANT, "tuition_missing_reference")
    _, result = pay(services, student)
    assert result.transfer_state == PaymentState.DELIVERED
    return result.payment_id


def submission(transfer_alias):
    return CaseSubmission(payment_id=transfer_alias, obligation_id=OBLIGATION, evidence_ids=())


def ready_case(services, student, transfer_alias):
    case = services.cases.create(student, submission(transfer_alias))
    assert case.state == CaseState.READY
    return case


def test_a_delivered_payment_with_a_lost_reference_is_unmatched_and_unpaid(services, student):
    delivered_without_reference(services, student)
    snapshot = obligation(services.database)
    assert snapshot.obligation.state == TuitionState.EXCEPTION
    assert scalar(services.database, "SELECT count(*) FROM unmatched_payments") == 1
    assert scalar(services.database, "SELECT count(*) FROM university_postings") == 0


def test_recovery_posts_the_tuition_once_with_no_extra_debit(services, student):
    transfer = delivered_without_reference(services, student)
    held = services.intents.create(student, proposal())
    assert (
        isinstance(held, Created)
        and held.decision.reason_code == ReasonCode.RECONCILIATION_NEEDS_INFO
    )
    case = ready_case(services, student, transfer)
    submitted = services.cases.submit(student, case.id)
    assert submitted.state == CaseState.SUBMITTED
    assert obligation(services.database).obligation.state == TuitionState.RECONCILIATION_PENDING
    assert scalar(services.database, "SELECT count(*) FROM university_postings") == 0

    assert services.review.review_submitted(TENANT) == [case.id]

    db = services.database
    assert scalar(db, "SELECT state FROM reconciliation_cases") == "RESOLVED"
    assert scalar(db, "SELECT count(*) FROM university_postings") == 1
    assert scalar(db, "SELECT match_status FROM university_receipts") == "RECONCILED"
    assert obligation(db).obligation.state == TuitionState.PAID
    assert count(db, "transfers") == 1 and balance(db) == OPENING - TOTAL
    assert (
        scalar(db, "SELECT count(*) FROM audit_events WHERE action = 'RECONCILIATION_REVIEWED'")
        == 1
    )


def test_reviewing_again_never_posts_a_second_time(services, student):
    case = ready_case(services, student, delivered_without_reference(services, student))
    services.cases.submit(student, case.id)
    services.review.review_case(TENANT, case.id)
    assert services.review.review_case(TENANT, case.id) == CaseState.RESOLVED
    assert scalar(services.database, "SELECT count(*) FROM university_postings") == 1


def test_parallel_reviews_post_exactly_once(services, student):
    case = ready_case(services, student, delivered_without_reference(services, student))
    services.cases.submit(student, case.id)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(services.review.review_case, TENANT, case.id) for _ in range(6)]
        assert {future.result() for future in futures} == {CaseState.RESOLVED}
    assert scalar(services.database, "SELECT count(*) FROM university_postings") == 1


def test_a_conflicting_receipt_amount_escalates_and_never_claims_payment(services, student):
    case = ready_case(services, student, delivered_without_reference(services, student))
    services.cases.submit(student, case.id)
    with services.database.connection() as connection:
        connection.execute("UPDATE university_receipts SET received_minor = received_minor - 1")
    assert services.review.review_case(TENANT, case.id) == CaseState.ESCALATED
    assert scalar(services.database, "SELECT reviewer_reason FROM reconciliation_cases") == (
        ReviewReason.AMOUNT_CONFLICT.value
    )
    assert scalar(services.database, "SELECT count(*) FROM university_postings") == 0
    assert obligation(services.database).obligation.state == TuitionState.ESCALATED


def test_a_case_without_a_delivered_receipt_waits_for_evidence(services, student):
    with services.database.connection() as connection:
        set_fault(connection, TENANT, "mock_remit_a", FaultMode.TIMEOUT_AFTER_ACCEPT)
    _, result = pay(services, student)
    case = services.cases.create(student, submission(result.payment_id))
    assert case.state == CaseState.EVIDENCE_REQUIRED
    assert {"AMOUNT", "RECEIPT"} <= set(case.evidence_missing)
    assert services.cases.submit(student, case.id).state == CaseState.EVIDENCE_REQUIRED
    assert scalar(services.database, "SELECT count(*) FROM university_postings") == 0


def test_opening_the_case_twice_returns_the_same_case(services, student):
    transfer = delivered_without_reference(services, student)
    assert ready_case(services, student, transfer).id == ready_case(services, student, transfer).id
    assert count(services.database, "reconciliation_cases") == 1


def test_only_the_owning_student_can_open_a_case(services, student, sponsor):
    transfer = delivered_without_reference(services, student)
    with pytest.raises(ScopeDenied):
        services.cases.create(sponsor, submission(transfer))


def test_a_student_cannot_resolve_or_post_through_the_case_service(services):
    assert not hasattr(services.cases, "review_case")
    assert not hasattr(services.cases, "post_receipt")


def test_an_unauthorized_actor_cannot_trigger_a_review_for_an_unsubmitted_case(services, student):
    case = ready_case(services, student, delivered_without_reference(services, student))
    assert services.review.review_case(TENANT, case.id) == CaseState.READY
    assert scalar(services.database, "SELECT count(*) FROM university_postings") == 0
    assert authorize and Refused
