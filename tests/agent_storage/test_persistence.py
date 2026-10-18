import asyncio
import json
import os
import subprocess
import sys
import threading

import pytest
from psycopg.types.json import Jsonb

from backend.agent.migrations import migrate_agent_storage
from backend.agent.persistence import PostgresConversations, PostgresRuns, _lock_id
from backend.agent.state import TuitionDraft
from backend.authz.service import AuthService
from backend.contracts.enums import Intent
from backend.contracts.http import AgentResponse, ToolEvent
from backend.contracts.models import ScopeDenied, ServiceUnavailable
from backend.demo.reset import reset_demo_fixture
from tests.agent_storage.conftest import PASSWORD


def response(run_id="run_one"):
    return AgentResponse(
        run_id=run_id,
        requested_action=Intent.TUITION,
        message="PRIVATE original chat secret sk-test-private user@example.org",
        tool_events=(ToolEvent(tool="clarify_tuition", status="PENDING"),),
    )


def counts(env):
    with env.database.connection() as connection:
        return tuple(
            connection.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
            for table in ("agent_conversations", "agent_runs")
        )


async def complete(store, key, run_id="run_one", amount=1):
    async with store.turn(key) as session:
        session.state = session.state.model_copy(
            update={
                "active_intent": Intent.TUITION,
                "tuition": TuitionDraft(requested_amount_minor=amount),
            }
        )
        session.response = response(run_id)


async def test_restart_recovers_typed_state_and_run_without_prose(env):
    await complete(PostgresConversations(env.database, env.auth), env.key())
    async with PostgresConversations(env.database, env.auth).turn(env.key()) as session:
        assert session.state.tuition.requested_amount_minor == 1
    result = await PostgresRuns(env.database, env.auth).get("run_one", env.login.actor)
    assert result.requested_action == Intent.TUITION
    assert "Original chat text is not retained" in result.message
    with env.database.connection() as connection:
        raw = connection.execute("SELECT metadata FROM agent_runs").fetchone()["metadata"]
        assert not any(term in json.dumps(raw) for term in ("PRIVATE", "sk-test", "@", "message"))
    assert counts(env) == (1, 1)


async def test_actual_process_recreation_recovers_committed_state(env):
    await complete(PostgresConversations(env.database, env.auth), env.key())
    code = """
import asyncio, os
from backend.agent.persistence import PostgresConversations
from backend.agent.state import ConversationKey
from backend.authz.storage import Database
from backend.authz.service import AuthService
async def main():
    db = Database(os.environ['AGENT_TEST_DSN'])
    key = ConversationKey.model_validate_json(os.environ['AGENT_TEST_KEY'])
    async with PostgresConversations(db, AuthService(db, key.tenant_id)).turn(key) as session:
        assert session.state.tuition.requested_amount_minor == 1
asyncio.run(main())
"""
    child_env = os.environ.copy()
    child_env.update(AGENT_TEST_DSN=env.database.dsn, AGENT_TEST_KEY=env.key().model_dump_json())
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", code],
        env=child_env,
        capture_output=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")


async def test_conversation_namespaces_and_run_access_are_isolated(env):
    store = PostgresConversations(env.database, env.auth)
    await complete(store, env.key())
    another_login = env.auth.login("student", PASSWORD, "another-login")
    second = env.auth.login("second", PASSWORD, "another-student")
    other_auth = AuthService(env.database, "demo_other")
    other = other_auth.login("student", PASSWORD, "another-tenant")
    async with store.turn(env.key("different_conversation")) as session:
        assert session.state.active_intent is None
    for key, auth, actor in (
        (env.key(actor=another_login.actor), env.auth, another_login.actor),
        (env.key(actor=second.actor), env.auth, second.actor),
        (env.key(actor=other.actor), other_auth, other.actor),
    ):
        async with PostgresConversations(env.database, auth).turn(key) as session:
            assert session.state.active_intent is None
        with pytest.raises(ScopeDenied):
            await PostgresRuns(env.database, auth).get("run_one", actor)
    forged = env.key().model_copy(update={"actor_id": "stu_002"})
    with pytest.raises(ScopeDenied):
        async with store.turn(forged):
            pass


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE auth_sessions SET revoked_at = clock_timestamp()",
        "UPDATE auth_sessions SET expires_at = clock_timestamp() - interval '1 second'",
        "UPDATE auth_credentials SET version = version + 1",
        "UPDATE actors SET scopes = ARRAY['payment:propose']",
        "UPDATE actors SET active = false",
    ],
)
async def test_current_authority_required_for_both_reads_and_writes(env, mutation):
    store = PostgresConversations(env.database, env.auth)
    runs = PostgresRuns(env.database, env.auth)
    await complete(store, env.key())
    with env.database.connection() as connection:
        connection.execute(mutation)
    for operation in (
        runs.get("run_one", env.login.actor),
        runs.put(response("run_two"), env.login.actor),
    ):
        with pytest.raises(ScopeDenied):
            await operation
    with pytest.raises(ScopeDenied):
        async with store.turn(env.key()):
            pass
    assert counts(env) == (1, 1)


async def test_sponsor_cannot_read_or_write_student_agent_storage(env):
    sponsor = env.auth.login("sponsor", PASSWORD, "sponsor")
    with pytest.raises(ScopeDenied):
        await PostgresRuns(env.database, env.auth).put(response(), sponsor.actor)
    with pytest.raises(ScopeDenied):
        async with PostgresConversations(env.database, env.auth).turn(env.key(actor=sponsor.actor)):
            pass
    assert counts(env) == (0, 0)


async def test_revocation_during_model_wait_is_not_blocked_and_prevents_commit(env):
    store = PostgresConversations(env.database, env.auth)
    with pytest.raises(ScopeDenied):
        async with store.turn(env.key()) as session:
            session.state = session.state.model_copy(update={"active_intent": Intent.TUITION})
            session.response = response()
            await asyncio.wait_for(asyncio.to_thread(env.auth.logout, env.login.token), timeout=2)
    assert counts(env) == (0, 0)


async def test_ttl_capacity_and_reset_invalidation_preserve_historical_runs(env):
    store = PostgresConversations(env.database, env.auth, capacity=1)
    await complete(store, env.key())
    with pytest.raises(ServiceUnavailable, match="capacity"):
        await complete(store, env.key("other"), "run_two")
    with env.database.connection() as connection:
        row = connection.execute(
            "SELECT d.expires_at <= s.expires_at AS bounded FROM agent_conversations d "
            "JOIN auth_sessions s USING (session_id)"
        ).fetchone()
        assert row["bounded"]
        connection.execute("UPDATE agent_conversations SET expires_at = clock_timestamp()")
    async with store.turn(env.key()) as session:
        assert session.state.active_intent is None
    await complete(store, env.key(), "run_two")
    with env.database.connection() as connection:
        connection.execute("UPDATE demo_state SET run_no = run_no + 1")
    async with store.turn(env.key()) as session:
        assert session.state.active_intent is None
    assert counts(env) == (0, 2)


async def test_two_workers_serialize_completed_turns(env):
    first = PostgresConversations(env.database, env.auth)
    second = PostgresConversations(env.database, env.auth)
    entered = asyncio.Event()

    async def writer():
        async with first.turn(env.key()) as session:
            entered.set()
            await asyncio.sleep(0.05)
            session.state = session.state.model_copy(update={"active_intent": Intent.TUITION})
            session.response = response()

    async def follower():
        await asyncio.wait_for(entered.wait(), timeout=5)
        async with second.turn(env.key()) as session:
            assert session.state.active_intent == Intent.TUITION
            session.response = response("run_two")

    await asyncio.gather(writer(), follower())
    assert counts(env) == (1, 2)


async def test_lock_timeout_then_release_does_not_poison_later_turns(env):
    store = PostgresConversations(env.database, env.auth, lock_wait_seconds=0.05)
    async with store.turn(env.key()):
        with pytest.raises(ServiceUnavailable):
            async with store.turn(env.key()):
                pass
    await complete(store, env.key())
    assert counts(env) == (1, 1)


async def test_run_failure_rolls_back_state_update_atomically(env, monkeypatch):
    store = PostgresConversations(env.database, env.auth)

    def fail(*args):
        raise ServiceUnavailable("forced run write failure")

    monkeypatch.setattr(store, "_record", fail)
    with pytest.raises(ServiceUnavailable):
        await complete(store, env.key())
    assert counts(env) == (0, 0)


async def test_model_cancellation_rolls_back_and_releases_the_worker_lock(env):
    store = PostgresConversations(env.database, env.auth)
    entered = asyncio.Event()

    async def pending():
        async with store.turn(env.key()) as session:
            session.state = session.state.model_copy(update={"active_intent": Intent.TUITION})
            session.response = response()
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(pending())
    await asyncio.wait_for(entered.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert counts(env) == (0, 0)
    await complete(store, env.key())


async def test_cancellation_before_database_commit_leaves_neither_record(env, monkeypatch):
    store = PostgresConversations(env.database, env.auth)
    started, release = threading.Event(), threading.Event()
    original = store._save

    def delayed(*args):
        started.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(store, "_save", delayed)
    task = asyncio.create_task(complete(store, env.key()))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert counts(env) == (0, 0)


async def test_conflicting_run_or_revision_cannot_overwrite_history(env):
    store = PostgresConversations(env.database, env.auth)
    runs = PostgresRuns(env.database, env.auth)
    await complete(store, env.key())
    await runs.put(response(), env.login.actor)  # Router's second write is idempotent.
    with pytest.raises(ServiceUnavailable):
        await runs.put(
            response().model_copy(update={"requested_action": Intent.TRACK}), env.login.actor
        )
    with pytest.raises(ServiceUnavailable):
        async with store.turn(env.key()) as session:
            with env.database.connection() as connection:
                connection.execute("UPDATE agent_conversations SET revision = revision + 1")
            session.response = response("run_two")
    assert counts(env) == (1, 1)
    with pytest.raises(ServiceUnavailable):
        with env.database.connection() as connection:
            connection.execute("DELETE FROM agent_runs")


@pytest.mark.parametrize("bad", [{"unknown": "PRIVATE"}, {"active_intent": "EXECUTE"}])
async def test_corrupt_state_fails_closed_without_echoing_payload(env, bad):
    store = PostgresConversations(env.database, env.auth)
    await complete(store, env.key())
    with env.database.connection() as connection:
        connection.execute("UPDATE agent_conversations SET state = %s", (Jsonb(bad),))
    with pytest.raises(ServiceUnavailable) as error:
        async with store.turn(env.key()):
            pass
    assert "PRIVATE" not in str(error.value)


async def test_oversized_state_and_unknown_schema_are_rejected(env):
    store = PostgresConversations(env.database, env.auth)
    with pytest.raises(ServiceUnavailable):
        async with store.turn(env.key()) as session:
            session.state = session.state.model_copy(
                update={"tuition": TuitionDraft(obligation_options=("obl_long_identifier",) * 5000)}
            )
            session.response = response()
    assert counts(env) == (0, 0)
    await complete(store, env.key())
    with env.database.connection() as connection:
        connection.execute("UPDATE agent_conversations SET schema_version = 2")
    with pytest.raises(ServiceUnavailable):
        async with store.turn(env.key()):
            pass


async def test_run_history_survives_identity_cleanup_and_migration_is_repeatable(env):
    await complete(PostgresConversations(env.database, env.auth), env.key())
    migrate_agent_storage(env.database)
    with env.database.connection() as connection:
        connection.execute("DELETE FROM actors WHERE actor_id = 'stu_001'")
    assert counts(env) == (0, 1)
    with pytest.raises(ScopeDenied):
        await PostgresRuns(env.database, env.auth).get("run_one", env.login.actor)


async def test_state_expiry_uses_idle_ttl_and_never_outlives_current_session(env):
    store = PostgresConversations(env.database, env.auth)
    await complete(store, env.key())
    with env.database.connection() as connection:
        row = connection.execute(
            "SELECT updated_at, expires_at FROM agent_conversations"
        ).fetchone()
        assert 1799 <= (row["expires_at"] - row["updated_at"]).total_seconds() <= 1801
        connection.execute(
            "UPDATE auth_sessions SET expires_at = clock_timestamp() + interval '1 minute'"
        )
    await complete(store, env.key(), "run_two")
    with env.database.connection() as connection:
        assert connection.execute(
            "SELECT d.expires_at = s.expires_at AS equal FROM agent_conversations d "
            "JOIN auth_sessions s USING (session_id)"
        ).fetchone()["equal"]


async def test_simultaneous_new_conversations_cannot_exceed_tenant_capacity(env):
    both_entered, release = asyncio.Event(), asyncio.Event()
    entered = []

    async def contender(name):
        async with PostgresConversations(env.database, env.auth, capacity=1).turn(
            env.key(name)
        ) as session:
            entered.append(name)
            if len(entered) == 2:
                both_entered.set()
            await asyncio.wait_for(release.wait(), timeout=5)
            session.response = response("run_" + name)

    tasks = [asyncio.create_task(contender(name)) for name in ("one", "two")]
    await asyncio.wait_for(both_entered.wait(), timeout=5)
    assert counts(env) == (0, 0)  # No placeholder states are committed while the model is running.
    release.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert sum(item is None for item in results) == 1
    assert sum(isinstance(item, ServiceUnavailable) for item in results) == 1
    assert counts(env) == (1, 1)


async def test_actual_simulator_reset_during_turn_prevents_stale_commit(env):
    store = PostgresConversations(env.database, env.auth)
    with pytest.raises(ServiceUnavailable, match="Scenario changed"):
        async with store.turn(env.key()) as session:
            session.response = response()
            await asyncio.to_thread(
                reset_demo_fixture, env.database, "demo_001", "tuition_happy_path"
            )
    assert counts(env) == (0, 0)
    await complete(store, env.key())
    with env.database.connection() as connection:
        assert (
            connection.execute("SELECT scenario_run_no FROM agent_runs").fetchone()[
                "scenario_run_no"
            ]
            == 1
        )


async def test_conflicting_actor_cannot_replace_a_run_and_unknown_run_schema_fails_closed(env):
    runs = PostgresRuns(env.database, env.auth)
    await runs.put(response(), env.login.actor)
    second = env.auth.login("second", PASSWORD, "second-student")
    with pytest.raises(ScopeDenied):
        await runs.put(response(), second.actor)
    with env.database.connection() as connection:
        connection.execute(
            "INSERT INTO agent_runs (run_id, tenant_id, actor_id, session_id, "
            "scenario_run_no, metadata) "
            "VALUES ('run_corrupt', %s, %s, %s, 0, %s)",
            (
                env.login.actor.tenant_id,
                env.login.actor.actor_id,
                env.login.actor.session_id,
                Jsonb({"schema_version": 2, "requested_action": None}),
            ),
        )
    with pytest.raises(ServiceUnavailable, match="diagnostics unavailable"):
        await runs.get("run_corrupt", env.login.actor)
    with pytest.raises(ServiceUnavailable):
        with env.database.connection() as connection:
            connection.execute("UPDATE agent_runs SET metadata = '{}'::jsonb")


async def test_missing_run_table_rolls_back_draft_without_in_memory_fallback(env):
    with env.database.connection() as connection:
        connection.execute("ALTER TABLE agent_runs RENAME TO agent_runs_unavailable")
    try:
        with pytest.raises(ServiceUnavailable):
            await complete(PostgresConversations(env.database, env.auth), env.key())
    finally:
        with env.database.connection() as connection:
            connection.execute("ALTER TABLE agent_runs_unavailable RENAME TO agent_runs")
    assert counts(env) == (0, 0)


async def test_session_expiring_while_waiting_for_capacity_cannot_load_a_draft(env, monkeypatch):
    store = PostgresConversations(env.database, env.auth)
    await complete(store, env.key())
    preparing = threading.Event()
    original = store._prepare

    def prepare(*args):
        preparing.set()  # The initial current-session check has already passed.
        return original(*args)

    monkeypatch.setattr(store, "_prepare", prepare)
    with env.database.connection() as connection:
        connection.execute(
            "UPDATE auth_sessions SET expires_at = clock_timestamp() + interval '1 second'"
        )
    entered = []

    async def reader():
        async with store.turn(env.key()) as session:
            entered.append(session.state.tuition.requested_amount_minor)

    with env.database.connection() as blocker:
        blocker.execute(
            "SELECT pg_advisory_xact_lock(%s)", (_lock_id("agent-capacity", ("demo_001",)),)
        )
        task = asyncio.create_task(reader())
        assert await asyncio.to_thread(preparing.wait, 5)
        await asyncio.sleep(1.05)
        blocker.commit()
        with pytest.raises(ScopeDenied):
            await task
    assert not entered
