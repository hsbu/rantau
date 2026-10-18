"""Explicit isolated-demo bootstrap, never invoked by application startup."""

import argparse

from backend.authz.passwords import hash_password
from backend.authz.storage import Database, migrate
from backend.config import Settings


def provision_demo(
    database: Database, student_password: str, sponsor_password: str, app_env: str
) -> None:
    if app_env not in {"development", "test"}:
        raise ValueError("Demo bootstrap is restricted to development/test")
    if student_password == sponsor_password:
        raise ValueError("Student and sponsor require distinct credentials")
    credentials = (
        (
            "stu_001",
            "STUDENT",
            ["student:read", "payment:propose", "payment:execute", "reconciliation:submit"],
            "student",
            hash_password(student_password),
        ),
        (
            "par_001",
            "SPONSOR",
            ["sponsor:read", "sponsor:approve", "payment:execute", "mandate:manage"],
            "sponsor",
            hash_password(sponsor_password),
        ),
    )
    with database.connection() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(714202602)")
        if connection.execute("SELECT 1 FROM actors WHERE tenant_id = 'demo_001'").fetchone():
            raise ValueError("Demo tenant already exists; bootstrap will not overwrite authority")
        for actor_id, role, scopes, username, password_hash in credentials:
            connection.execute(
                "INSERT INTO actors (tenant_id, actor_id, role, scopes) "
                "VALUES ('demo_001', %s, %s, %s)",
                (actor_id, role, scopes),
            )
            connection.execute(
                "INSERT INTO auth_credentials (tenant_id, actor_id, username, password_hash) "
                "VALUES ('demo_001', %s, %s, %s)",
                (actor_id, username, password_hash),
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Explicit Rantau isolated-demo authentication setup"
    )
    parser.add_argument("--migrate", action="store_true")
    parser.add_argument("--seed", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    if not (args.migrate or args.seed) or settings.app_env not in {"development", "test"}:
        parser.error("Select --migrate/--seed in development/test only")
    if not settings.database_url or settings.auth_tenant_id != "demo_001":
        parser.error(
            "Configure DATABASE_URL for an isolated demo database and AUTH_TENANT_ID=demo_001"
        )
    if args.seed and not (
        settings.auth_demo_student_password and settings.auth_demo_sponsor_password
    ):
        parser.error("Configure both local demo passwords before seeding")
    database = Database(settings.database_url.get_secret_value())
    try:
        if args.migrate:
            migrate(database)
        if args.seed:
            assert settings.auth_demo_student_password and settings.auth_demo_sponsor_password
            provision_demo(
                database,
                settings.auth_demo_student_password.get_secret_value(),
                settings.auth_demo_sponsor_password.get_secret_value(),
                settings.app_env,
            )
    except (ValueError, OSError):
        raise SystemExit(
            "Demo setup failed; inspect local configuration without sharing credentials"
        ) from None


if __name__ == "__main__":
    main()
