"""Explicit migration composition; imports do not migrate or seed a database."""

import hashlib
from pathlib import Path

from backend.authz.storage import Database
from backend.config import Settings
from backend.finance.migrations import migrate_all


def migrate_agent_storage(database: Database) -> None:
    migrate_all(database)
    for version in ("020_agent_storage", "021_agent_actions"):
        _apply(database, version)


def _apply(database: Database, version: str) -> None:
    raw = (Path(__file__).resolve().parents[2] / "migrations" / f"{version}.sql").read_bytes()
    raw = raw.replace(b"\r\n", b"\n")
    checksum = hashlib.sha256(raw).hexdigest()
    with database.connection() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(714202620)")
        previous = connection.execute(
            "SELECT checksum FROM rantau_migrations WHERE version = %s", (version,)
        ).fetchone()
        if previous is None:
            connection.execute(raw.decode("utf-8"))
            connection.execute(
                "INSERT INTO rantau_migrations VALUES (%s, %s)", (version, checksum)
            )
        elif previous["checksum"] != checksum:
            raise ValueError("Applied agent migration checksum differs")


def main() -> None:
    settings = Settings()
    if not settings.database_url:
        raise SystemExit("Configure DATABASE_URL locally before explicitly migrating storage.")
    migrate_agent_storage(Database(settings.database_url.get_secret_value()))


if __name__ == "__main__":
    main()
