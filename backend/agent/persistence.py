"""PostgreSQL drafts and diagnostics; no financial writes or cached authority."""

import asyncio
import hashlib
import json
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from backend.agent.run_records import MAX_RUN_BYTES, RunRecord, project_run
from backend.agent.state import ConversationKey, ConversationSession, ConversationState
from backend.authz.policy_repository import PolicyConnection
from backend.authz.service import AuthService
from backend.authz.storage import Database
from backend.contracts.enums import Role
from backend.contracts.http import AgentResponse
from backend.contracts.models import ActorContext, ScopeDenied, ServiceUnavailable

MAX_STATE_BYTES = 64 * 1024
SCOPE = "tenant_id = %s AND actor_id = %s AND session_id = %s"
KEY = SCOPE + " AND conversation_id = %s"


def _lock_id(namespace: str, parts: tuple[str, ...]) -> int:
    digest = hashlib.sha256(json.dumps((namespace, *parts)).encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


async def _database_call[T](
    call: Callable[[], T],
    stopped: threading.Event | None = None,
    on_cancel: Callable[[T], None] | None = None,
) -> T:
    # Wait for a running DB worker to finish before releasing the conversation lock.
    task = asyncio.create_task(asyncio.to_thread(call))
    interrupted = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            interrupted = True
            if stopped is not None:
                stopped.set()
        except Exception:
            if not interrupted:
                raise
            break
    if interrupted:
        if not task.cancelled():
            error = task.exception()
            if error is None and on_cancel is not None:
                await _database_call(lambda: on_cancel(task.result()))
        raise asyncio.CancelledError
    return task.result()


class _Storage:
    def __init__(self, database: Database, auth: AuthService) -> None:
        self.database = database
        self.auth = auth

    def _require(self, connection: PolicyConnection, actor: ActorContext) -> datetime:
        if actor.tenant_id != self.auth.tenant_id:
            raise ScopeDenied("Resource unavailable")
        self.auth.current_actor(connection, actor)
        if actor.role != Role.STUDENT or "student:read" not in actor.scopes:
            raise ScopeDenied("Resource unavailable")
        row = connection.execute(
            "SELECT expires_at FROM auth_sessions WHERE session_id = %s", (actor.session_id,)
        ).fetchone()
        assert row is not None
        expires: datetime = row["expires_at"]
        return expires

    def _actor(self, connection: PolicyConnection, key: ConversationKey) -> ActorContext:
        row = connection.execute(
            "SELECT a.role, a.scopes FROM actors a JOIN auth_sessions s "
            "USING (tenant_id, actor_id) WHERE s.tenant_id = %s AND s.actor_id = %s "
            "AND s.session_id = %s",
            (key.tenant_id, key.actor_id, key.session_id),
        ).fetchone()
        if row is None:
            raise ScopeDenied("Resource unavailable")
        actor = ActorContext(
            tenant_id=key.tenant_id,
            actor_id=key.actor_id,
            session_id=key.session_id,
            role=row["role"],
            scopes=frozenset(row["scopes"]),
        )
        self._require(connection, actor)
        return actor

    @staticmethod
    def _scenario(connection: PolicyConnection, tenant_id: str) -> int:
        row = connection.execute(
            "SELECT run_no FROM demo_state WHERE tenant_id = %s FOR SHARE", (tenant_id,)
        ).fetchone()
        return int(row["run_no"]) if row is not None else 0

    @staticmethod
    def _record(
        connection: PolicyConnection,
        response: AgentResponse,
        actor: ActorContext,
        conversation_id: str | None,
        scenario: int,
    ) -> None:
        metadata = project_run(response).model_dump(mode="json")
        connection.execute(
            "INSERT INTO agent_runs (run_id, tenant_id, actor_id, session_id, conversation_id, "
            "scenario_run_no, metadata) VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id) DO NOTHING",
            (
                response.run_id,
                actor.tenant_id,
                actor.actor_id,
                actor.session_id,
                conversation_id,
                scenario,
                Jsonb(metadata),
            ),
        )
        row = connection.execute(
            "SELECT * FROM agent_runs WHERE run_id = %s", (response.run_id,)
        ).fetchone()
        assert row is not None
        if any(
            row[name] != getattr(actor, name) for name in ("tenant_id", "actor_id", "session_id")
        ):
            raise ScopeDenied("Resource unavailable")
        if row["metadata"] != metadata or (
            conversation_id is not None
            and (row["conversation_id"] != conversation_id or row["scenario_run_no"] != scenario)
        ):
            raise ServiceUnavailable("Conflicting agent run diagnostics")


class PostgresRuns(_Storage):
    """Append-only metadata, accessible only through the original current student session."""

    async def put(self, response: AgentResponse, actor: ActorContext) -> None:
        await _database_call(lambda: self._put(response, actor))

    def _put(self, response: AgentResponse, actor: ActorContext) -> None:
        with self.database.connection() as connection:
            self._require(connection, actor)
            self._record(
                connection, response, actor, None, self._scenario(connection, actor.tenant_id)
            )
            self._require(connection, actor)

    async def get(self, run_id: str, actor: ActorContext) -> AgentResponse:
        return await _database_call(lambda: self._get(run_id, actor))

    def _get(self, run_id: str, actor: ActorContext) -> AgentResponse:
        with self.database.connection() as connection:
            self._require(connection, actor)
            row = connection.execute(
                f"SELECT metadata FROM agent_runs WHERE run_id = %s AND {SCOPE}",
                (run_id, actor.tenant_id, actor.actor_id, actor.session_id),
            ).fetchone()
            if row is None:
                raise ScopeDenied("Resource unavailable")
            try:
                if len(json.dumps(row["metadata"]).encode()) > MAX_RUN_BYTES:
                    raise ValueError("Oversized metadata")
                record = RunRecord.model_validate(row["metadata"])
                response = project_run(record.response(run_id)).response(run_id)
            except (ValueError, TypeError):
                raise ServiceUnavailable("Agent diagnostics unavailable") from None
            self._require(connection, actor)
            return response


@dataclass(frozen=True)
class _Snapshot:
    state: ConversationState
    revision: int | None
    scenario: int
    actor: ActorContext


class PostgresConversations(_Storage):
    """A session advisory lock spans the turn; auth/state transactions remain short."""

    def __init__(
        self,
        database: Database,
        auth: AuthService,
        *,
        capacity: int = 128,
        ttl_seconds: int = 1800,
        lock_wait_seconds: float = 5,
    ) -> None:
        super().__init__(database, auth)
        if (
            not 1 <= capacity <= 128
            or not 1 <= ttl_seconds <= 1800
            or not 0 < lock_wait_seconds <= 5
        ):
            raise ValueError("Invalid conversation storage bounds")
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        self.lock_wait_seconds = lock_wait_seconds

    @asynccontextmanager
    async def _locked(self, parts: tuple[str, ...]) -> AsyncIterator[None]:
        timeout_ms = max(1, int(self.lock_wait_seconds * 1000))
        # Synchronous psycopg in workers also supports Windows' default Proactor loop.
        # The dedicated connection holds only a session advisory lock, not a transaction.
        connection = await _database_call(
            lambda: psycopg.connect(
                self.database.dsn,
                autocommit=True,
                row_factory=dict_row,
                connect_timeout=3,
                options=f"-c statement_timeout={timeout_ms} -c lock_timeout={timeout_ms}",
            ),
            on_cancel=lambda value: value.close(),
        )
        try:
            await _database_call(
                lambda: connection.execute(
                    "SELECT pg_advisory_lock(%s)", (_lock_id("agent-conversation", parts),)
                )
            )
            yield
        finally:
            await _database_call(connection.close)

    @asynccontextmanager
    async def turn(self, key: ConversationKey) -> AsyncIterator[ConversationSession]:
        try:
            key = ConversationKey.model_validate(key.model_dump())
            parts = (key.tenant_id, key.actor_id, key.session_id, key.conversation_id)
            async with self._locked(parts):
                snapshot = await _database_call(lambda: self._load(key))
                session = ConversationSession(state=snapshot.state)
                yield session
                if session.response is None:
                    if session.state != snapshot.state:
                        raise ServiceUnavailable("Completed run diagnostics are required")
                else:
                    stopped = threading.Event()
                    await _database_call(
                        lambda: self._save(key, snapshot, session, stopped), stopped
                    )
        except (psycopg.Error, ValidationError):
            raise ServiceUnavailable("Agent conversation storage unavailable") from None

    def _prepare(self, connection: PolicyConnection, tenant_id: str, scenario: int) -> None:
        connection.execute(
            "SELECT pg_advisory_xact_lock(%s)", (_lock_id("agent-capacity", (tenant_id,)),)
        )
        connection.execute(
            "DELETE FROM agent_conversations d WHERE d.tenant_id = %s AND "
            "(d.expires_at <= clock_timestamp() OR d.scenario_run_no <> %s OR NOT EXISTS ("
            "SELECT 1 FROM auth_sessions s JOIN actors a USING (tenant_id, actor_id) "
            "JOIN auth_credentials c USING (tenant_id, actor_id) WHERE s.session_id = d.session_id "
            "AND s.tenant_id = d.tenant_id AND s.actor_id = d.actor_id AND a.active "
            "AND a.role = 'STUDENT' AND 'student:read' = ANY(a.scopes) "
            "AND s.revoked_at IS NULL AND s.expires_at > clock_timestamp() "
            "AND s.credential_version = c.version))",
            (tenant_id, scenario),
        )

    def _capacity(self, connection: PolicyConnection, key: ConversationKey) -> None:
        count = connection.execute(
            "SELECT count(*) AS n FROM agent_conversations WHERE tenant_id = %s", (key.tenant_id,)
        ).fetchone()
        assert count is not None
        if count["n"] >= self.capacity:
            raise ServiceUnavailable("Conversation capacity reached")

    def _load(self, key: ConversationKey) -> _Snapshot:
        with self.database.connection() as connection:
            actor = self._actor(connection, key)
            scenario = self._scenario(connection, key.tenant_id)
            self._prepare(connection, key.tenant_id, scenario)
            row = connection.execute(
                f"SELECT state, revision, schema_version FROM agent_conversations WHERE {KEY}",
                (key.tenant_id, key.actor_id, key.session_id, key.conversation_id),
            ).fetchone()
            if row is None:
                self._capacity(connection, key)
                self._require(connection, actor)
                return _Snapshot(ConversationState(), None, scenario, actor)
            try:
                if (
                    row["schema_version"] != 1
                    or len(json.dumps(row["state"]).encode()) > MAX_STATE_BYTES
                ):
                    raise ValueError("Unsupported state")
                state = ConversationState.model_validate(row["state"])
            except (ValueError, TypeError):
                raise ServiceUnavailable("Conversation state unavailable") from None
            self._require(connection, actor)
            return _Snapshot(state, row["revision"], scenario, actor)

    def _save(
        self,
        key: ConversationKey,
        snapshot: _Snapshot,
        session: ConversationSession,
        stopped: threading.Event,
    ) -> None:
        try:
            state = ConversationState.model_validate(
                session.state.model_dump(mode="json", warnings="error")
            )
            if len(state.model_dump_json().encode()) > MAX_STATE_BYTES:
                raise ValueError("Oversized state")
        except (ValueError, TypeError):
            raise ServiceUnavailable("Conversation state unavailable") from None
        assert session.response is not None
        with self.database.connection() as connection:
            expires = self._require(connection, snapshot.actor)
            scenario = self._scenario(connection, key.tenant_id)
            if scenario != snapshot.scenario:
                raise ServiceUnavailable("Scenario changed during the conversation turn")
            self._prepare(connection, key.tenant_id, scenario)
            params = (key.tenant_id, key.actor_id, key.session_id, key.conversation_id)
            payload = Jsonb(state.model_dump(mode="json"))
            if snapshot.revision is None:
                self._capacity(connection, key)
                row = connection.execute(
                    "INSERT INTO agent_conversations (tenant_id, actor_id, session_id, "
                    "conversation_id, revision, scenario_run_no, state, expires_at) "
                    "VALUES (%s, %s, %s, %s, 1, %s, %s, LEAST(%s, clock_timestamp() "
                    "+ %s * interval '1 second')) ON CONFLICT DO NOTHING RETURNING revision",
                    (*params, scenario, payload, expires, self.ttl_seconds),
                ).fetchone()
            else:
                row = connection.execute(
                    "UPDATE agent_conversations SET state = %s, revision = revision + 1, "
                    "updated_at = clock_timestamp(), expires_at = LEAST(%s, clock_timestamp() "
                    f"+ %s * interval '1 second') WHERE {KEY} AND revision = %s RETURNING revision",
                    (payload, expires, self.ttl_seconds, *params, snapshot.revision),
                ).fetchone()
            if row is None:
                raise ServiceUnavailable("Conversation changed during the turn")
            self._record(
                connection, session.response, snapshot.actor, key.conversation_id, scenario
            )
            self._require(connection, snapshot.actor)
            if stopped.is_set():
                raise ServiceUnavailable("Conversation turn cancelled before commit")
