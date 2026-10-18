"""Security state/audit assertions against real disposable PostgreSQL storage."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier

import psycopg
import pytest

from backend.authz.storage import migrate
from backend.contracts.enums import Role
from backend.contracts.models import ScopeDenied, ServiceUnavailable
from backend.fraud.security_cases import SecurityCaseDecision, SecurityReason
from backend.fraud.security_store import SecurityCaseConflict
from tests.fraud.conftest import actor

REASON = SecurityReason.PROMPT_INJECTION


@contextmanager
def transaction(database):
    with database.connection() as connection, connection.transaction():
        yield connection


def records(database, table):
    assert table in {"security_holds", "security_cases", "security_events"}
    with database.connection() as connection:
        return connection.execute("SELECT * FROM " + table + " ORDER BY id").fetchall()


def test_case_review_audit_stays_correlated_with_held_resource(
    security, database, student, reviewer
):
    with transaction(database) as connection:
        case = security.create_case(connection, student, "resource_001", REASON)
        security.decide_case(
            connection, reviewer, case.case_id, SecurityCaseDecision.UNDER_REVIEW, REASON
        )
    events = records(database, "security_events")
    assert len(events) == 2
    assert {event["resource_id"] for event in events} == {"resource_001"}
    assert {event["actor_id"] for event in events} == {student.actor_id, reviewer.actor_id}


@pytest.mark.parametrize(
    "assignment", ["cleared_by = 'other_reviewer'", "cleared_at = cleared_at + interval '1 hour'"]
)
def test_cleared_hold_reviewer_and_timestamp_cannot_be_rewritten(
    security, database, student, reviewer, assignment
):
    with transaction(database) as connection:
        hold = security.place_hold(connection, student, "resource_001", REASON)
        security.clear_hold(connection, reviewer, hold.hold_id, REASON)
    original = records(database, "security_holds")
    with transaction(database) as connection:
        with pytest.raises(psycopg.Error), connection.transaction():
            connection.execute("UPDATE security_holds SET " + assignment)
    assert records(database, "security_holds") == original


def test_migrations_replay_without_losing_security_history(security, database, student):
    with transaction(database) as connection:
        security.place_hold(connection, student, "resource_001", REASON)
        security.create_case(connection, student, "resource_001", REASON, ("evidence_001",))
    before = {table: records(database, table) for table in SECURITY_TABLES}
    migrate(database)
    assert {table: records(database, table) for table in SECURITY_TABLES} == before
    with transaction(database) as connection:
        versions = connection.execute(
            "SELECT version FROM rantau_migrations ORDER BY version"
        ).fetchall()
        assert [row["version"] for row in versions] == [
            "001_auth",
            "002_policy_audit",
            "003_authority",
            "004_security_cases",
            "005_security_history_guards",
        ]


SECURITY_TABLES = ("security_holds", "security_cases", "security_events")


def test_hold_retry_clear_retry_and_new_hold_keep_one_event_per_change(
    security, database, student, reviewer
):
    with transaction(database) as connection:
        first = security.place_hold(connection, student, "resource_001", REASON)
        assert security.place_hold(connection, student, "resource_001", REASON) == first
    assert len(records(database, "security_events")) == 1
    with transaction(database) as connection:
        cleared = security.clear_hold(connection, reviewer, first.hold_id, REASON)
        assert cleared.state == "CLEARED" and cleared.cleared_by == reviewer.actor_id
        assert cleared.cleared_at is not None
        assert security.clear_hold(connection, reviewer, first.hold_id, REASON) == cleared
    assert len(records(database, "security_events")) == 2
    with transaction(database) as connection:
        second = security.place_hold(connection, student, "resource_001", REASON)
    assert first.hold_id != second.hold_id
    assert [row["state"] for row in records(database, "security_holds")].count("ACTIVE") == 1
    events = records(database, "security_events")
    assert len(events) == 3
    assert all(row["resource_id"] == "resource_001" for row in events)
    clear_event = next(row for row in events if row["action"] == "HOLD_CLEARED")
    assert clear_event["actor_id"] == reviewer.actor_id
    assert clear_event["decision"] == "CLEAR_HOLD" and clear_event["reason_code"] == REASON


@pytest.mark.parametrize(
    "unauthorized",
    [
        actor(),
        actor("par_001", role=Role.SPONSOR, scopes={"sponsor:read", "security:review"}),
        actor("stu_001", scopes={"student:read", "security:review"}),
        actor("reviewer_001", role=Role.DEMO_ADMIN, scopes=set()),
    ],
    ids=["student", "sponsor-with-review-scope", "student-with-review-scope", "admin-no-scope"],
)
def test_role_and_scope_are_both_required_to_clear_or_decide(
    security, database, student, unauthorized
):
    with transaction(database) as connection:
        hold = security.place_hold(connection, student, "resource_001", REASON)
        case = security.create_case(connection, student, "resource_001", REASON)
        with pytest.raises(ScopeDenied):
            security.clear_hold(connection, unauthorized, hold.hold_id, REASON)
        with pytest.raises(ScopeDenied):
            security.decide_case(
                connection, unauthorized, case.case_id, SecurityCaseDecision.RESOLVED, REASON
            )
    assert records(database, "security_holds")[0]["state"] == "ACTIVE"
    assert records(database, "security_cases")[0]["state"] == "OPEN"
    assert len(records(database, "security_events")) == 2


def test_cases_and_holds_are_isolated_for_unrelated_actors_and_tenants(
    security, database, student, reviewer
):
    foreign_student = actor(tenant="other_tenant")
    foreign_reviewer = reviewer.model_copy(update={"tenant_id": "other_tenant"})
    stranger = actor("stu_other")
    with transaction(database) as connection:
        own = security.create_case(connection, student, "resource_001", REASON)
        foreign = security.create_case(connection, foreign_student, "resource_001", REASON)
        hold = security.place_hold(connection, student, "resource_001", REASON)
        foreign_hold = security.place_hold(connection, foreign_student, "resource_001", REASON)
        assert foreign_hold.hold_id != hold.hold_id
        assert security.list_cases(connection, student) == (own,)
        assert security.list_cases(connection, foreign_reviewer) == (foreign,)
        assert security.list_cases(connection, stranger) == ()
        for requester in (stranger, foreign_student, foreign_reviewer):
            with pytest.raises(ScopeDenied, match="Resource unavailable"):
                security.get_case(connection, requester, own.case_id)
        with pytest.raises(ScopeDenied):
            security.clear_hold(connection, foreign_reviewer, hold.hold_id, REASON)
        with pytest.raises(ScopeDenied):
            security.decide_case(
                connection, foreign_reviewer, own.case_id, SecurityCaseDecision.RESOLVED, REASON
            )
        for operation in (security.place_hold, security.create_case):
            with pytest.raises(ScopeDenied):
                operation(connection, student, "resource_other", REASON)
    assert len(records(database, "security_events")) == 4
    assert {row["state"] for row in records(database, "security_holds")} == {"ACTIVE"}


@pytest.mark.parametrize(
    "requester",
    [
        actor(scopes=set()),
        actor(role=Role.SPONSOR, scopes=set()),
        actor(role=Role.DEMO_ADMIN, scopes=set()),
    ],
)
def test_case_read_requires_role_specific_scope(security, database, student, requester):
    with transaction(database) as connection:
        case = security.create_case(connection, student, "resource_001", REASON)
        with pytest.raises(ScopeDenied):
            security.get_case(connection, requester, case.case_id)
        with pytest.raises(ScopeDenied):
            security.list_cases(connection, requester)


def test_sponsor_can_hold_owned_resource_but_review_scope_cannot_place(
    security, database, reviewer
):
    sponsor = actor("par_001", role=Role.SPONSOR, scopes={"sponsor:read", "security:hold"})
    with transaction(database) as connection:
        hold = security.place_hold(connection, sponsor, "resource_sponsor", REASON)
        assert hold.created_by == sponsor.actor_id
        with pytest.raises(ScopeDenied):
            security.place_hold(connection, sponsor, "resource_001", REASON)
        with pytest.raises(ScopeDenied):
            security.place_hold(connection, reviewer, "resource_001", REASON)


def test_case_lifecycle_is_audited_and_resolved_case_cannot_reopen(
    security, database, student, reviewer
):
    decisions = [
        SecurityCaseDecision.UNDER_REVIEW,
        SecurityCaseDecision.ESCALATED,
        SecurityCaseDecision.UNDER_REVIEW,
        SecurityCaseDecision.RESOLVED,
    ]
    with transaction(database) as connection:
        case = security.create_case(connection, student, "resource_001", REASON, ("evidence_001",))
        for decision in decisions:
            case = security.decide_case(connection, reviewer, case.case_id, decision, REASON)
            assert case.state.value == decision.value
        assert (
            security.decide_case(
                connection, reviewer, case.case_id, SecurityCaseDecision.RESOLVED, REASON
            )
            == case
        )
        with pytest.raises(SecurityCaseConflict):
            security.decide_case(
                connection, reviewer, case.case_id, SecurityCaseDecision.ESCALATED, REASON
            )
    assert len(records(database, "security_events")) == 5
    assert records(database, "security_cases")[0]["evidence_ids"] == ["evidence_001"]


@pytest.mark.parametrize("operation", ["place", "create", "clear", "decide"])
@pytest.mark.parametrize("failure", ["application", "database"])
def test_audit_failure_rolls_back_security_state_with_caller_transaction(
    security, database, student, reviewer, monkeypatch, operation, failure
):
    with transaction(database) as connection:
        hold = security.place_hold(connection, student, "resource_001", REASON)
        case = security.create_case(connection, student, "resource_001", REASON)
    before = {table: records(database, table) for table in SECURITY_TABLES}

    def fail_audit(connection, *args):
        if failure == "database":
            connection.execute("SELECT 1 / 0")
        raise RuntimeError("Synthetic audit failure")

    monkeypatch.setattr(security.repository, "_append_event", fail_audit)
    expected = ServiceUnavailable if failure == "database" else RuntimeError
    with pytest.raises(expected):
        with transaction(database) as connection:
            if operation == "place":
                security.place_hold(connection, actor("stu_other"), "resource_other", REASON)
            elif operation == "create":
                security.create_case(connection, student, "resource_001", REASON)
            elif operation == "clear":
                security.clear_hold(connection, reviewer, hold.hold_id, REASON)
            else:
                security.decide_case(
                    connection, reviewer, case.case_id, SecurityCaseDecision.RESOLVED, REASON
                )
    assert {table: records(database, table) for table in SECURITY_TABLES} == before


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE security_events SET actor_id = 'forged_actor'",
        "DELETE FROM security_events",
        "DELETE FROM security_cases",
        "DELETE FROM security_holds",
        "UPDATE security_cases SET evidence_ids = ARRAY['forged_evidence']",
        "UPDATE security_cases SET resource_id = 'resource_other'",
        "UPDATE security_holds SET reason_code = 'POLICY_REVIEW'",
    ],
)
def test_database_blocks_history_tampering(security, database, student, statement):
    with transaction(database) as connection:
        security.place_hold(connection, student, "resource_001", REASON)
        security.create_case(connection, student, "resource_001", REASON)
    before = {table: records(database, table) for table in SECURITY_TABLES}
    with transaction(database) as connection:
        with pytest.raises(psycopg.Error), connection.transaction():
            connection.execute(statement)
    assert {table: records(database, table) for table in SECURITY_TABLES} == before


@pytest.mark.parametrize(
    "evidence",
    [("duplicate", "duplicate"), ("raw secret text",), tuple(f"ref_{n}" for n in range(21))],
)
def test_invalid_evidence_rejected_before_any_storage_write(security, database, student, evidence):
    with transaction(database) as connection:
        with pytest.raises(ValueError):
            security.create_case(connection, student, "resource_001", REASON, evidence)
    assert all(records(database, table) == [] for table in SECURITY_TABLES)


def test_storage_rejects_idle_autocommit_and_closed_connections(security, database, student):
    with database.connection() as connection:
        with pytest.raises(ServiceUnavailable):
            security.place_hold(connection, student, "resource_001", REASON)
        connection.autocommit = True
        with pytest.raises(ServiceUnavailable):
            security.place_hold(connection, student, "resource_001", REASON)
    with pytest.raises(ServiceUnavailable):
        security.place_hold(connection, student, "resource_001", REASON)
    assert not records(database, "security_holds")


@pytest.mark.parametrize("operation", ["place", "clear", "resolve"])
def test_concurrent_retries_produce_one_state_change_and_event(
    security, database, student, reviewer, operation
):
    with transaction(database) as connection:
        hold = None
        if operation != "place":
            hold = security.place_hold(connection, student, "resource_001", REASON)
        case = security.create_case(connection, student, "resource_001", REASON)
    barrier = Barrier(2)

    def attempt():
        barrier.wait(timeout=10)
        with transaction(database) as connection:
            if operation == "place":
                return security.place_hold(connection, student, "resource_001", REASON)
            if operation == "clear":
                assert hold is not None
                return security.clear_hold(connection, reviewer, hold.hold_id, REASON)
            return security.decide_case(
                connection, reviewer, case.case_id, SecurityCaseDecision.RESOLVED, REASON
            )

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(attempt) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert results[0] == results[1]
    events = records(database, "security_events")
    assert len(events) == (2 if operation == "place" else 3)
