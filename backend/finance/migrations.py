"""Apply B's auth migrations unchanged, then C's finance and university migrations."""

import hashlib
from pathlib import Path

from backend.authz.storage import Database, migrate

FINANCE_MIGRATIONS = ("010_audit_events", "011_finance_core", "012_university")
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
FINANCE_MIGRATION_LOCK = 714202603


def migrate_all(database: Database) -> None:
    migrate(database)
    with database.connection() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (FINANCE_MIGRATION_LOCK,))
        for version in FINANCE_MIGRATIONS:
            raw = (MIGRATIONS_DIR / f"{version}.sql").read_bytes().replace(b"\r\n", b"\n")
            checksum = hashlib.sha256(raw).hexdigest()
            previous = connection.execute(
                "SELECT checksum FROM rantau_migrations WHERE version = %s", (version,)
            ).fetchone()
            if previous is None:
                connection.execute(raw.decode("utf-8"))
                connection.execute(
                    "INSERT INTO rantau_migrations VALUES (%s, %s)", (version, checksum)
                )
            elif previous["checksum"] != checksum:
                raise ValueError("Applied migration checksum differs")
