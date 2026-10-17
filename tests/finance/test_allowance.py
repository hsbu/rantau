import pytest

from backend.contracts.enums import Decision, PaymentState, ReasonCode, Tier
from backend.contracts.models import IntentProposal, ScopeDenied
from backend.finance.outcomes import Created, Executed, Refused
from backend.finance.quotes import QuoteService
from tests.finance.conftest import TENANT
from tests.finance.factories import authorize, balance, count, proposal, scalar

ALLOWANCE_FEN = 100_000
ALLOWANCE_TOTAL = 2_325_000
OPENING = 150_000_000
ALLOWANCE_PAYEE = "benef_stu_001_allowance"


def allowance(services, beneficiary=ALLOWANCE_PAYEE, obligation_id=None):
    with services.database.connection() as connection:
        quote = QuoteService().issue(connection, TENANT, ALLOWANCE_FEN)[0]
    return IntentProposal(
        obligation_id=obligation_id,
        source_account_id="acct_idr_01",
        beneficiary_id=beneficiary,
        quote_id=quote.id,
        purpose="ALLOWANCE",
    )


def test_a_routine_allowance_under_a_mandate_needs_no_per_transfer_approval(services, student):
    services.authority.mandate_limits = (5_000_000, 10_000_000, 20_000_000)
    created = services.intents.create(student, allowance(services))
    assert isinstance(created, Created)
    assert (created.decision.decision, created.intent.tier) == (Decision.ALLOW, Tier.T1)
    result = services.executor.execute(student, created.intent.id, "key-allow-1")
    assert isinstance(result, Executed) and result.transfer_state == PaymentState.DELIVERED
    assert balance(services.database) == OPENING - ALLOWANCE_TOTAL
    assert scalar(services.database, "SELECT blocks_obligation FROM transfers") is False
    assert count(services.database, "university_receipts") == 0


def test_without_a_mandate_an_allowance_needs_the_owners_approval(services, student):
    created = services.intents.create(student, allowance(services))
    assert created.decision.decision == Decision.REQUIRE_APPROVAL and created.intent.tier == Tier.T2
    refused = services.executor.execute(student, created.intent.id, "key-allow-2")
    assert isinstance(refused, Refused) and balance(services.database) == OPENING
    authorize(services, created.intent.id)
    assert isinstance(
        services.executor.execute(student, created.intent.id, "key-allow-2"), Executed
    )


def test_split_allowances_cannot_exceed_the_mandate_cumulatively(services, student):
    services.authority.mandate_limits = (5_000_000, 5_000_000, 20_000_000)
    outcomes = []
    for index in range(3):
        created = services.intents.create(student, allowance(services))
        outcomes.append(services.executor.execute(student, created.intent.id, f"key-split-{index}"))
    assert [isinstance(outcome, Executed) for outcome in outcomes] == [True, True, False]
    assert outcomes[2].reason_code == ReasonCode.FUNDING_OWNER_APPROVAL_REQUIRED
    assert balance(services.database) == OPENING - 2 * ALLOWANCE_TOTAL


def test_an_allowance_must_go_to_the_students_own_verified_recipient(services, student):
    for payee in ("benef_uni_cn_01", "benef_attacker_account"):
        outcome = services.intents.create(student, allowance(services, beneficiary=payee))
        assert isinstance(outcome, Refused)
        assert outcome.reason_code == ReasonCode.UNKNOWN_BENEFICIARY
    assert count(services.database, "payment_intents") == 0


def test_tuition_cannot_be_paid_to_the_allowance_recipient(services, student):
    outcome = services.intents.create(student, proposal(beneficiary=ALLOWANCE_PAYEE))
    assert isinstance(outcome, Refused) and outcome.reason_code == ReasonCode.UNKNOWN_BENEFICIARY


def test_an_allowance_cannot_name_an_obligation(services, student):
    with pytest.raises(ScopeDenied):
        services.intents.create(student, allowance(services, obligation_id="obl_2026_demo_01"))


def test_a_delivered_allowance_does_not_hold_up_the_tuition_payment(services, student):
    services.authority.mandate_limits = (5_000_000, 10_000_000, 20_000_000)
    created = services.intents.create(student, allowance(services))
    services.executor.execute(student, created.intent.id, "key-allow-3")
    tuition = services.intents.create(student, proposal())
    assert isinstance(tuition, Created) and tuition.intent.state == PaymentState.AWAITING_APPROVAL
