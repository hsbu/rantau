"""Database-backed session authority and revocable student sharing consent."""

import hashlib
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

import psycopg

from backend.authz.passwords import hash_password, verify_password
from backend.authz.storage import Database
from backend.contracts.auth import SHARED_FIELDS, ConsentSummary, SharedField
from backend.contracts.enums import Role
from backend.contracts.models import ActorContext, ScopeDenied

_DUMMY_HASH = hash_password("unused-dummy-credential-for-timing")
_ACTOR_QUERY = """
    SELECT a.actor_id, a.tenant_id, a.role, a.scopes, s.session_id
    FROM auth_sessions s
    JOIN actors a USING (tenant_id, actor_id)
    JOIN auth_credentials c USING (tenant_id, actor_id)
    WHERE a.active AND s.revoked_at IS NULL AND s.expires_at > clock_timestamp()
      AND s.credential_version = c.version AND s.tenant_id = %s
"""


class InvalidSession(Exception):
    """Generic authentication failure; no credential/identity details."""


class LoginThrottled(Exception):
    """Persistent login attempt limit reached."""


@dataclass(frozen=True)
class LoginSession:
    token: str = field(repr=False)
    actor: ActorContext


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _actor(row: dict[str, Any]) -> ActorContext:
    return ActorContext(
        actor_id=row["actor_id"],
        tenant_id=row["tenant_id"],
        session_id=row["session_id"],
        role=row["role"],
        scopes=frozenset(row["scopes"]),
    )


class AuthService:
    def __init__(self, database: Database, tenant_id: str) -> None:
        self.database = database
        self.tenant_id = tenant_id

    def _limit_attempt(self, username: str, peer: str) -> None:
        # A committed atomic reservation bounds password work across workers.
        # Client buckets are checked first so rotating names cannot create unlimited rows.
        for label, value, limit in (("peer", peer, 30), ("user", username, 5)):
            key = _digest(f"{self.tenant_id}\0{label}\0{value}")
            with self.database.connection() as connection:
                connection.execute(
                    "DELETE FROM auth_login_attempts "
                    "WHERE window_started < now() - interval '1 day'"
                )
                row = connection.execute(
                    """INSERT INTO auth_login_attempts (bucket, attempts) VALUES (%s, 1)
                    ON CONFLICT (bucket) DO UPDATE SET
                        attempts = CASE WHEN auth_login_attempts.window_started <=
                            now() - interval '15 minutes' THEN 1
                            ELSE LEAST(auth_login_attempts.attempts + 1, 1000000) END,
                        window_started = CASE WHEN auth_login_attempts.window_started <=
                            now() - interval '15 minutes' THEN now()
                            ELSE auth_login_attempts.window_started END
                    RETURNING attempts""",
                    (key,),
                ).fetchone()
                assert row is not None
                count = row["attempts"]
            if count > limit:
                raise LoginThrottled()

    def login(self, username: str, password: str, peer: str) -> LoginSession:
        if not re.fullmatch(r"[a-z0-9_.-]{1,64}", username) or not 1 <= len(password) <= 128:
            raise InvalidSession()
        self._limit_attempt(username, peer)
        with self.database.connection() as connection:
            record = connection.execute(
                """SELECT a.actor_id, a.tenant_id, a.role, a.scopes, a.active,
                    c.password_hash, c.version
                FROM auth_credentials c JOIN actors a USING (tenant_id, actor_id)
                WHERE c.tenant_id = %s AND c.username = %s FOR SHARE OF a, c""",
                (self.tenant_id, username),
            ).fetchone()
            valid = verify_password(password, record["password_hash"] if record else _DUMMY_HASH)
            if record is None or not valid or not record["active"]:
                raise InvalidSession()
            token = secrets.token_urlsafe(32)
            session_id = f"session_{uuid4().hex}"
            connection.execute(
                """INSERT INTO auth_sessions
                (session_id, token_digest, tenant_id, actor_id, credential_version)
                VALUES (%s, %s, %s, %s, %s)""",
                (session_id, _digest(token), self.tenant_id, record["actor_id"], record["version"]),
            )
            return LoginSession(token, _actor(record | {"session_id": session_id}))

    def authenticate(self, token: str | None) -> ActorContext:
        if token is None or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise InvalidSession()
        with self.database.connection() as connection:
            row = connection.execute(
                _ACTOR_QUERY + " AND s.token_digest = %s", (self.tenant_id, _digest(token))
            ).fetchone()
            if row is None:
                raise InvalidSession()
            return _actor(row)

    def logout(self, token: str) -> None:
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE auth_sessions SET revoked_at = now() "
                "WHERE tenant_id = %s AND token_digest = %s",
                (self.tenant_id, _digest(token)),
            )

    def current_actor(
        self, connection: psycopg.Connection[dict[str, Any]], actor: ActorContext
    ) -> None:
        row = connection.execute(
            _ACTOR_QUERY + " AND s.session_id = %s FOR SHARE OF s, a, c",
            (self.tenant_id, actor.session_id),
        ).fetchone()
        if row is None or _actor(row) != actor:
            raise ScopeDenied("Resource unavailable")

    def grant_consent(
        self,
        actor: ActorContext,
        sponsor_id: str,
        fields: frozenset[SharedField],
        expires_at: datetime,
    ) -> ConsentSummary:
        if not fields or not fields <= SHARED_FIELDS or expires_at.utcoffset() is None:
            raise ValueError("Invalid sharing request")
        with self.database.connection() as connection:
            self.current_actor(connection, actor)
            if actor.role != Role.STUDENT or "student:read" not in actor.scopes:
                raise ScopeDenied("Resource unavailable")
            now = connection.execute("SELECT now() AS current_time").fetchone()
            assert now is not None
            if expires_at <= now["current_time"]:
                raise ValueError("Consent must expire in the future")
            sponsor = connection.execute(
                "SELECT actor_id FROM actors WHERE tenant_id = %s AND actor_id = %s "
                "AND role = 'SPONSOR' AND active FOR SHARE",
                (actor.tenant_id, sponsor_id),
            ).fetchone()
            if sponsor is None:
                raise ScopeDenied("Resource unavailable")
            connection.execute(
                """INSERT INTO student_sponsor_consents
                (tenant_id, student_id, sponsor_id, allowed_shared_fields, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, student_id, sponsor_id) DO UPDATE SET
                    allowed_shared_fields = EXCLUDED.allowed_shared_fields,
                    expires_at = EXCLUDED.expires_at, revoked_at = NULL""",
                (actor.tenant_id, actor.actor_id, sponsor_id, sorted(fields), expires_at),
            )
        return ConsentSummary(
            sponsor_id=sponsor_id, allowed_shared_fields=fields, expires_at=expires_at
        )

    def revoke_consent(self, actor: ActorContext, sponsor_id: str) -> None:
        with self.database.connection() as connection:
            self.current_actor(connection, actor)
            if actor.role != Role.STUDENT:
                raise ScopeDenied("Resource unavailable")
            connection.execute(
                "UPDATE student_sponsor_consents SET revoked_at = now() "
                "WHERE tenant_id = %s AND student_id = %s AND sponsor_id = %s",
                (actor.tenant_id, actor.actor_id, sponsor_id),
            )

    def ready(self) -> bool:
        from backend.contracts.models import ServiceUnavailable

        try:
            with self.database.connection() as connection:
                connection.execute(
                    "SELECT a.tenant_id, a.role, a.scopes, a.active, c.password_hash, c.version, "
                    "s.session_id, s.token_digest, s.expires_at, s.revoked_at, "
                    "g.allowed_shared_fields, g.expires_at, g.revoked_at, "
                    "l.attempts, l.window_started FROM actors a, auth_credentials c, "
                    "auth_sessions s, student_sponsor_consents g, auth_login_attempts l WHERE false"
                )
                return bool(
                    connection.execute(
                        "SELECT 1 FROM rantau_migrations WHERE version = '001_auth'"
                    ).fetchone()
                )
        except ServiceUnavailable:
            return False
