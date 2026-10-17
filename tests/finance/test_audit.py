import psycopg
import pytest

from backend.finance.audit import AuditEvent, AuditWriter

TENANT = "demo_001"


def event(**overrides):
    fields = {
        "tenant_id": TENANT,
        "actor_id": "stu_001",
        "action": "PAYMENT_DEBITED",
        "resource_type": "transfer",
        "resource_id": "transfer_001",
        "decision": "ALLOW",
    }
    return AuditEvent(**(fields | overrides))


def test_record_returns_a_stable_audit_alias_and_stores_the_row(finance_db):
    with finance_db.connection() as connection:
        audit_id = AuditWriter().record(connection, event())
        row = connection.execute("SELECT * FROM audit_events").fetchone()
    assert audit_id.startswith("audit_")
    assert (row["audit_event_id"], row["action"], row["tenant_id"]) == (
        audit_id,
        "PAYMENT_DEBITED",
        TENANT,
    )


def test_audit_rows_cannot_be_changed_or_deleted(finance_db):
    with finance_db.connection() as connection:
        AuditWriter().record(connection, event())
    for statement in ("UPDATE audit_events SET action = 'X'", "DELETE FROM audit_events"):
        with pytest.raises(psycopg.Error, match="append-only"):
            with psycopg.connect(finance_db.dsn) as connection:
                connection.execute(statement)


def test_secret_looking_state_fields_are_redacted(finance_db):
    leaky = event(after_state={"balance_minor": 5, "masked_number": "••12", "state": "PROCESSING"})
    with finance_db.connection() as connection:
        AuditWriter().record(connection, leaky)
        stored = connection.execute("SELECT after_state FROM audit_events").fetchone()
    assert stored["after_state"] == {"state": "PROCESSING"}


def test_audit_tags_the_current_demo_run(seeded):
    with seeded.connection() as connection:
        AuditWriter().record(connection, event())
        run = connection.execute("SELECT run_no FROM demo_state").fetchone()["run_no"]
        stored = connection.execute("SELECT run_no FROM audit_events").fetchone()["run_no"]
    assert stored == run
