import pytest

from backend.contracts.enums import PaymentState, ReasonCode
from backend.contracts.models import ScopeDenied
from backend.finance.outcomes import Created, Refused
from backend.finance.states import InvalidTransition
from tests.finance.factories import authorize, count, proposal, scalar


def route_b_quote(services):
    from backend.finance.quotes import QuoteService
    from tests.finance.conftest import TENANT

    with services.database.connection() as connection:
        return QuoteService().issue(connection, TENANT, 2_000_000)[1].id


def test_a_revision_replaces_the_old_intent_and_voids_its_approval(services, student):
    old = services.intents.create(student, proposal()).intent
    authorize(services, old.id)
    revised = services.intents.revise(student, old.id, proposal(quote=route_b_quote(services)))
    assert isinstance(revised, Created)
    assert revised.intent.intent_revision == 2 and revised.intent.terms_hash != old.terms_hash
    assert revised.intent.state == PaymentState.AWAITING_APPROVAL
    assert (
        scalar(services.database, "SELECT state FROM payment_intents WHERE alias = %s", (old.id,))
        == "CANCELLED"
    )
    assert (
        scalar(
            services.database,
            "SELECT supersedes_alias FROM payment_intents WHERE alias = %s",
            (revised.intent.id,),
        )
        == old.id
    )
    stale = services.executor.execute(student, old.id, "key-old")
    assert isinstance(stale, Refused) and count(services.database, "transfers") == 0
    unapproved = services.executor.execute(student, revised.intent.id, "key-new")
    assert isinstance(unapproved, Refused)
    assert unapproved.reason_code == ReasonCode.FUNDING_OWNER_APPROVAL_REQUIRED


def test_a_started_payment_cannot_be_revised(services, student):
    old = services.intents.create(student, proposal()).intent
    authorize(services, old.id)
    services.executor.execute(student, old.id, "key-started")
    with pytest.raises(InvalidTransition):
        services.intents.revise(student, old.id, proposal(quote=route_b_quote(services)))
    assert count(services.database, "payment_intents") == 1


def test_a_revision_to_an_unverified_payee_leaves_the_original_untouched(services, student):
    old = services.intents.create(student, proposal()).intent
    outcome = services.intents.revise(student, old.id, proposal(beneficiary="benef_forged"))
    assert isinstance(outcome, Refused) and outcome.reason_code == ReasonCode.UNKNOWN_BENEFICIARY
    state = scalar(
        services.database, "SELECT state FROM payment_intents WHERE alias = %s", (old.id,)
    )
    assert state == "AWAITING_APPROVAL"


def test_only_the_requester_can_revise(services, student, sponsor):
    old = services.intents.create(student, proposal()).intent
    with pytest.raises(ScopeDenied):
        services.intents.revise(sponsor, old.id, proposal(quote=route_b_quote(services)))
