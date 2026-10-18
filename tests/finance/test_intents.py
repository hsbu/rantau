import psycopg
import pytest

from backend.contracts.enums import Decision, PaymentState, ReasonCode, Tier
from backend.contracts.models import ScopeDenied
from backend.finance.outcomes import Created, Refused
from backend.finance.states import InvalidTransition
from backend.finance.terms import canonical_terms_hash
from tests.finance.conftest import TENANT
from tests.finance.factories import authorize, count, proposal, scalar


def test_tuition_intent_needs_the_funding_owner_and_stores_hashed_terms(services, student):
    outcome = services.intents.create(student, proposal())
    assert isinstance(outcome, Created)
    intent = outcome.intent
    assert (intent.state, intent.tier) == (PaymentState.AWAITING_APPROVAL, Tier.T2)
    assert outcome.decision.decision == Decision.REQUIRE_APPROVAL
    assert intent.funding_owner_id == "par_001" and intent.requested_by == "stu_001"
    assert intent.terms_hash == canonical_terms_hash(intent)
    assert count(services.database, "payment_intents") == 1
    assert count(services.database, "audit_events") == 1


def test_amount_and_payee_come_from_the_server_not_the_proposal(services, student):
    intent = services.intents.create(student, proposal()).intent
    assert (intent.source_total_minor, intent.destination_amount_minor) == (46_025_000, 2_000_000)
    assert intent.beneficiary_fingerprint == "synthetic-beneficiary-fingerprint"


def test_unknown_beneficiary_is_held_and_no_intent_exists(services, student):
    outcome = services.intents.create(student, proposal(beneficiary="benef_attacker_new_account"))
    assert isinstance(outcome, Refused)
    assert outcome.reason_code == ReasonCode.UNKNOWN_BENEFICIARY
    assert count(services.database, "payment_intents") == 0
    assert count(services.database, "audit_events") == 1


def test_another_students_obligation_is_not_disclosed(services, student):
    with pytest.raises(ScopeDenied):
        services.intents.create(student, proposal(obligation="obl_not_mine"))


def test_a_sponsor_cannot_propose_a_payment(services, sponsor):
    with pytest.raises(ScopeDenied):
        services.intents.create(sponsor, proposal())


def test_terms_cannot_be_edited_after_creation(services, student):
    alias = services.intents.create(student, proposal()).intent.id
    with pytest.raises(psycopg.Error, match="immutable"):
        with psycopg.connect(services.database.dsn) as connection:
            connection.execute(
                "UPDATE payment_intents SET destination_amount_minor = 1 WHERE alias = %s",
                (alias,),
            )


def test_cancel_before_processing_is_allowed(services, student):
    alias = services.intents.create(student, proposal()).intent.id
    cancelled = services.intents.cancel(student, alias)
    assert cancelled.state == PaymentState.CANCELLED


def test_cancel_after_processing_is_rejected_and_nothing_changes(services, student):
    alias = services.intents.create(student, proposal()).intent.id
    authorize(services, alias)
    services.executor.execute(student, alias, "key-cancel-late")
    with pytest.raises(InvalidTransition):
        services.intents.cancel(student, alias)
    state = scalar(
        services.database,
        "SELECT state FROM payment_intents WHERE tenant_id = %s AND alias = %s",
        (TENANT, alias),
    )
    assert state == "DELIVERED"
