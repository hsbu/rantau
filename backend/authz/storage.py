"""Short PostgreSQL transactions; connection details never enter public exceptions."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from backend.contracts.models import ServiceUnavailable


class Database:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        try:
            with psycopg.connect(
                self.dsn,
                row_factory=dict_row,
                connect_timeout=3,
                options="-c statement_timeout=5000 -c lock_timeout=3000",
            ) as connection:
                yield connection
        except psycopg.Error:
            raise ServiceUnavailable("Authentication storage unavailable") from None


def migrate(database: Database) -> None:
    """Explicit migration only; callers must enforce the deployment's operator boundary."""
    with database.connection() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(714202601)")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS rantau_migrations "
            "(version text PRIMARY KEY, checksum text NOT NULL)"
        )
        for version in ("001_auth", "002_policy_audit", "003_authority"):
            path = Path(__file__).resolve().parents[2] / "migrations" / f"{version}.sql"
            raw = path.read_bytes().replace(b"\r\n", b"\n")
            checksum = hashlib.sha256(raw).hexdigest()
            previous = connection.execute(
                "SELECT checksum FROM rantau_migrations WHERE version = %s", (version,)
            ).fetchone()
            if previous:
                if previous["checksum"] != checksum:
                    raise ValueError("Applied migration checksum differs")
                continue
            connection.execute(raw.decode("utf-8"))
            connection.execute("INSERT INTO rantau_migrations VALUES (%s, %s)", (version, checksum))
