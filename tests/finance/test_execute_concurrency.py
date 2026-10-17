from concurrent.futures import ThreadPoolExecutor

from backend.contracts.enums import ReasonCode
from backend.finance.outcomes import Executed, Refused
from tests.finance.factories import (
    add_obligation,
    authorize,
    balance,
    count,
    proposal,
    scalar,
)

PARALLEL = 8
TOTAL = 46_025_000


def run_parallel(calls):
    barrier_free = ThreadPoolExecutor(max_workers=len(calls))
    with barrier_free as pool:
        return [future.result() for future in [pool.submit(call) for call in calls]]


def independent_intents(services, student, how_many):
    aliases = []
    for index in range(how_many):
        obligation = f"obl_parallel_{index}"
        quote = add_obligation(services.database, obligation, 2_000_000 + index * 1_000)
        created = services.intents.create(student, proposal(obligation=obligation, quote=quote))
        authorize(services, created.intent.id)
        aliases.append(created.intent.id)
    return aliases


def set_balance(database, minor):
    with database.connection() as connection:
        connection.execute("UPDATE funding_accounts SET balance_minor = %s", (minor,))


def test_parallel_payments_never_overdraw_the_account(services, student):
    aliases = independent_intents(services, student, PARALLEL)
    set_balance(services.database, 50_000_000)
    results = run_parallel(
        [
            lambda a=a, i=i: services.executor.execute(student, a, f"key-{i}")
            for i, a in enumerate(aliases)
        ]
    )
    assert sum(isinstance(r, Executed) for r in results) == 1
    assert all(
        r.reason_code == ReasonCode.INSUFFICIENT_FUNDS for r in results if isinstance(r, Refused)
    )
    assert 0 <= balance(services.database) < 50_000_000
    assert count(services.database, "transfers") == 1


def test_parallel_retries_of_one_key_make_exactly_one_debit(services, student):
    alias = independent_intents(services, student, 1)[0]
    results = run_parallel(
        [lambda: services.executor.execute(student, alias, "key-same")] * PARALLEL
    )
    assert all(isinstance(r, Executed) for r in results)
    assert len({r.payment_id for r in results}) == 1
    assert count(services.database, "transfers") == 1
    assert scalar(services.database, "SELECT count(*) FROM ledger_entries") == 3


def test_parallel_different_keys_cannot_pay_one_intent_twice(services, student):
    alias = independent_intents(services, student, 1)[0]
    results = run_parallel(
        [lambda i=i: services.executor.execute(student, alias, f"key-{i}") for i in range(PARALLEL)]
    )
    assert sum(isinstance(r, Executed) for r in results) == 1
    assert count(services.database, "transfers") == 1


def test_split_payments_cannot_evade_the_account_daily_limit(services, student):
    aliases = independent_intents(services, student, 4)
    with services.database.connection() as connection:
        connection.execute("UPDATE funding_accounts SET daily_limit_minor = 100_000_000")
    outcomes = [services.executor.execute(student, a, f"key-{i}") for i, a in enumerate(aliases)]
    assert sum(isinstance(o, Executed) for o in outcomes) == 2
    assert all(
        o.reason_code == ReasonCode.LIMIT_EXCEEDED for o in outcomes if isinstance(o, Refused)
    )
