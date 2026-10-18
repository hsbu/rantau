import pytest

from backend.demo.reset import reset_demo_fixture
from tests.finance.conftest import TENANT
from tests.finance.test_demo_reset import rows

HASH = "a" * 64


def insert_approval(database, approval_id, state):
    decided = state in {"APPROVED", "CONSUMED"}
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO approvals (approval_id, tenant_id, owner_id, intent_id, intent_revision,"
            " terms_hash, terms, review, state, expires_at, decision_actor_id, recorded_at,"
            " consumed_at) VALUES (%s, %s, 'par_001', %s, 1, %s, '{}', '{}', %s,"
            " now() + interval '1 hour', %s, %s, %s)",
            (
                approval_id,
                TENANT,
                "pay_" + approval_id,
                HASH,
                state,
                "par_001" if decided else None,
                connection.execute("SELECT now() AS t").fetchone()["t"] if decided else None,
                connection.execute("SELECT now() AS t").fetchone()["t"]
                if state == "CONSUMED"
                else None,
            ),
        )


def insert_hold(database, hold_id="hold_x"):
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO security_holds (hold_id, tenant_id, resource_id, reason_code, state,"
            " created_by, audit_event_id) VALUES (%s, %s, 'benef_unverified_01',"
            " 'UNKNOWN_BENEFICIARY', 'ACTIVE', 'par_001', 'audit_' || %s)",
            (hold_id, TENANT, hold_id),
        )


def insert_case(database, case_id="case_x"):
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO security_cases (case_id, tenant_id, resource_id, reason_code, state,"
            " opened_by, audit_event_id) VALUES (%s, %s, 'benef_unverified_01',"
            " 'SCAM_INDICATOR', 'OPEN', 'stu_001', 'audit_' || %s)",
            (case_id, TENANT, case_id),
        )


def insert_consent(database):
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO student_sponsor_consents (tenant_id, student_id, sponsor_id,"
            " allowed_shared_fields, expires_at) VALUES (%s, 'stu_001', 'par_001',"
            " ARRAY['tuition_summary'], now() + interval '1 day')",
            (TENANT,),
        )


def reset(database):
    reset_demo_fixture(database, TENANT, "tuition_happy_path")


@pytest.mark.parametrize("state", ["REQUESTED", "PENDING", "APPROVED"])
def test_an_open_approval_from_the_last_run_is_revoked(seeded, state):
    insert_approval(seeded, "appr_open", state)
    reset(seeded)
    assert rows(seeded, "SELECT state FROM approvals")[0]["state"] == "REVOKED"
    assert rows(seeded, "SELECT action FROM authority_events")[0]["action"] == "APPROVAL_REVOKED"


def test_a_consumed_approval_stays_as_history(seeded):
    insert_approval(seeded, "appr_done", "CONSUMED")
    reset(seeded)
    assert rows(seeded, "SELECT state FROM approvals")[0]["state"] == "CONSUMED"
    assert rows(seeded, "SELECT 1 FROM authority_events") == []


def test_an_active_hold_does_not_leak_into_the_next_run(seeded):
    insert_hold(seeded)
    reset(seeded)
    hold = rows(seeded, "SELECT * FROM security_holds")[0]
    assert hold["state"] == "CLEARED" and hold["cleared_by"] == "demo_reset"
    event = rows(seeded, "SELECT action, decision FROM security_events")[0]
    assert (event["action"], event["decision"]) == ("HOLD_CLEARED", "CLEAR_HOLD")


def test_an_open_case_is_resolved_with_an_audit_event(seeded):
    insert_case(seeded)
    reset(seeded)
    assert rows(seeded, "SELECT state FROM security_cases")[0]["state"] == "RESOLVED"
    assert rows(seeded, "SELECT decision FROM security_events")[0]["decision"] == "RESOLVE_CASE"


def test_consent_returns_to_the_default_of_no_sharing(seeded):
    insert_consent(seeded)
    reset(seeded)
    assert rows(seeded, "SELECT revoked_at FROM student_sponsor_consents")[0]["revoked_at"]


def test_identities_and_sessions_survive_the_reset(services):
    session = services.auth.login("student", "a-long-finance-test-password", "reset-tests")
    reset(services.database)
    assert len(rows(services.database, "SELECT 1 FROM actors")) == 2
    assert services.auth.authenticate(session.token).actor_id == "stu_001"


def test_a_second_reset_is_a_no_op_for_authority(seeded):
    insert_hold(seeded)
    reset(seeded)
    reset(seeded)
    assert len(rows(seeded, "SELECT 1 FROM security_events")) == 1
