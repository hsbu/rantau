from tests.finance.factories import authorize, balance, proposal, scalar

OPENING = 150_000_000


def test_every_transfer_has_balanced_legs_and_matches_the_account_balance(services, student):
    alias = services.intents.create(student, proposal()).intent.id
    authorize(services, alias)
    services.executor.execute(student, alias, "key-ledger")
    db = services.database
    unbalanced = scalar(
        db,
        "SELECT count(*) FROM (SELECT transfer_alias FROM ledger_entries GROUP BY transfer_alias "
        "HAVING sum(CASE direction WHEN 'DEBIT' THEN amount_minor ELSE -amount_minor END) <> 0) t",
    )
    debited = scalar(db, "SELECT sum(amount_minor) FROM ledger_entries WHERE leg = 'DEBIT_FUNDING'")
    assert unbalanced == 0
    assert balance(db) == OPENING - debited


def test_the_intent_and_its_transfer_report_the_same_state(services, student):
    alias = services.intents.create(student, proposal()).intent.id
    authorize(services, alias)
    services.executor.execute(student, alias, "key-state")
    assert scalar(
        services.database,
        "SELECT i.state = t.state FROM payment_intents i JOIN transfers t "
        "ON t.intent_alias = i.alias",
    )


def test_a_second_transfer_for_one_intent_or_obligation_is_impossible_at_the_database(
    services, student
):
    alias = services.intents.create(student, proposal()).intent.id
    authorize(services, alias)
    services.executor.execute(student, alias, "key-unique")
    import psycopg
    import pytest

    with pytest.raises(psycopg.errors.UniqueViolation):
        with psycopg.connect(services.database.dsn) as connection:
            connection.execute(
                "INSERT INTO transfers (tenant_id, alias, intent_alias, account_alias, "
                "obligation_alias, beneficiary_alias, provider, provider_reference, state, "
                "source_total_minor, destination_amount_minor) "
                "SELECT tenant_id, 'transfer_dup', 'intent_other', account_alias, "
                "obligation_alias, "
                "beneficiary_alias, provider, 'sim_ref_dup', 'PROCESSING', source_total_minor, "
                "destination_amount_minor FROM transfers"
            )
