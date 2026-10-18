from concurrent.futures import ThreadPoolExecutor

from backend.contracts.models import ScopeDenied, ServiceUnavailable
from backend.demo.reset import reset_demo_fixture
from tests.finance.conftest import TENANT
from tests.finance.factories import add_obligation, authorize, proposal, scalar

OPENING = 150_000_000
RACERS = 5


def attempt(call):
    try:
        return call()
    except (ScopeDenied, ServiceUnavailable) as error:
        return error


def test_a_reset_racing_with_payments_never_leaves_orphaned_money(services, student):
    aliases = []
    for index in range(RACERS):
        obligation = f"obl_race_{index}"
        quote = add_obligation(services.database, obligation, 2_000_000 + index * 1_000)
        created = services.intents.create(student, proposal(obligation=obligation, quote=quote))
        authorize(services, created.intent.id)
        aliases.append(created.intent.id)
    with ThreadPoolExecutor(max_workers=RACERS + 1) as pool:
        payments = [
            pool.submit(
                attempt, lambda a=a, i=i: services.executor.execute(student, a, f"key-race-{i}")
            )
            for i, a in enumerate(aliases)
        ]
        reset = pool.submit(
            attempt, lambda: reset_demo_fixture(services.database, TENANT, "tuition_happy_path")
        )
        for future in payments + [reset]:
            future.result()
    db = services.database
    orphan_ledger = scalar(
        db,
        "SELECT count(*) FROM ledger_entries l WHERE NOT EXISTS "
        "(SELECT 1 FROM transfers t WHERE t.alias = l.transfer_alias)",
    )
    orphan_transfers = scalar(
        db,
        "SELECT count(*) FROM transfers t WHERE NOT EXISTS "
        "(SELECT 1 FROM payment_intents i WHERE i.alias = t.intent_alias)",
    )
    debited = scalar(
        db, "SELECT COALESCE(sum(amount_minor), 0) FROM ledger_entries WHERE leg = 'DEBIT_FUNDING'"
    )
    balance = scalar(db, "SELECT balance_minor FROM funding_accounts WHERE alias = 'acct_idr_01'")
    assert orphan_ledger == 0 and orphan_transfers == 0
    assert balance == OPENING - debited
