from backend.demo.reset import reset_demo_fixture
from tests.finance.conftest import TENANT
from tests.finance.factories import authorize, balance, count, proposal, scalar

OPENING = 150_000_000


def test_a_reset_wipes_the_previous_run_but_keeps_its_audit_history(services, student):
    created = services.intents.create(student, proposal())
    authorize(services, created.intent.id)
    services.executor.execute(student, created.intent.id, "key-run-1")
    database = services.database
    old_audit = count(database, "audit_events")
    old_run = scalar(database, "SELECT run_no FROM demo_state")
    assert balance(database) < OPENING

    new_run = reset_demo_fixture(database, TENANT, "tuition_happy_path")

    assert new_run == old_run + 1
    assert balance(database) == OPENING
    for table in (
        "payment_intents",
        "transfers",
        "ledger_entries",
        "spend_entries",
        "idempotency_keys",
    ):
        assert count(database, table) == 0
    assert count(database, "audit_events") == old_audit
    assert scalar(database, "SELECT count(*) FROM audit_events WHERE run_no = %s", (new_run,)) == 0


def test_the_next_run_can_pay_the_same_obligation_again(services, student):
    first = services.intents.create(student, proposal()).intent.id
    authorize(services, first)
    services.executor.execute(student, first, "key-same-text")
    reset_demo_fixture(services.database, TENANT, "tuition_happy_path")
    services.authority.approved.clear()
    second = services.intents.create(student, proposal()).intent.id
    authorize(services, second)
    assert services.executor.execute(student, second, "key-same-text").replayed is False
    assert balance(services.database) < OPENING
