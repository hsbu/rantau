from backend.demo.reset import reset_demo_fixture
from backend.finance.wiring import build_services
from tests.finance.conftest import TENANT
from tests.finance.factories import balance, count, proposal

OPENING = 150_000_000


def test_planted_documents_are_returned_as_labelled_untrusted_data(services, student, sponsor):
    reset_demo_fixture(services.database, TENANT, "forged_beneficiary")
    reads = build_services(services.database, services.auth, services.authority).reads
    documents = reads.documents(student)
    assert len(documents) == 2 and {item.trust for item in documents} == {"UNTRUSTED"}
    assert any("new account" in item.body for item in documents)
    assert reads.documents(sponsor) == ()


def test_reading_injected_instructions_changes_no_payment_state(services, student):
    reset_demo_fixture(services.database, TENANT, "forged_beneficiary")
    reads = build_services(services.database, services.auth, services.authority).reads
    reads.documents(student)
    assert count(services.database, "payment_intents") == 0
    assert count(services.database, "transfers") == 0 and balance(services.database) == OPENING
    forged = services.intents.create(student, proposal(beneficiary="benef_unverified_01"))
    assert forged.intent.state.value == "ON_HOLD"
