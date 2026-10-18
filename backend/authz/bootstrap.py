"""Explicit isolated-demo bootstrap, never invoked by application startup."""

import argparse

from backend.authz.passwords import hash_password
from backend.authz.storage import Database, migrate
from backend.config import Settings

ADMIN_ACTOR_ID = "adm_001"
ADMIN_USERNAME = "admin"
# Least privilege: the demo administrator manages the simulation and nothing financial.
ADMIN_SCOPES = ["demo:manage"]
ADMIN_PASSWORD_LENGTH = range(12, 129)


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


def provision_demo_admin(
    database: Database, admin_password: str, app_env: str, tenant_id: str = "demo_001"
) -> None:
    """Add only the demo administrator to an existing tenant; never overwrite anything."""
    if app_env not in {"development", "test"}:
        raise ValueError("Demo bootstrap is restricted to development/test")
    if len(admin_password) not in ADMIN_PASSWORD_LENGTH:
        raise ValueError("Admin credential must be 12-128 characters")
    with database.connection() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(714202602)")
        if connection.execute(
            "SELECT 1 FROM actors WHERE tenant_id = %s AND actor_id = %s",
            (tenant_id, ADMIN_ACTOR_ID),
        ).fetchone():
            raise ValueError("Demo admin already exists; bootstrap will not overwrite it")
        connection.execute(
            "INSERT INTO actors (tenant_id, actor_id, role, scopes) "
            "VALUES (%s, %s, 'DEMO_ADMIN', %s)",
            (tenant_id, ADMIN_ACTOR_ID, ADMIN_SCOPES),
        )
        connection.execute(
            "INSERT INTO auth_credentials (tenant_id, actor_id, username, password_hash) "
            "VALUES (%s, %s, %s, %s)",
            (tenant_id, ADMIN_ACTOR_ID, ADMIN_USERNAME, hash_password(admin_password)),
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Explicit Rantau isolated-demo authentication setup"
    )
    parser.add_argument("--migrate", action="store_true")
    parser.add_argument("--seed", action="store_true")
    parser.add_argument(
        "--seed-admin",
        action="store_true",
        help="add only the demo administrator to an existing tenant",
    )
    args = parser.parse_args()
    settings = Settings()
    selected = args.migrate or args.seed or args.seed_admin
    if not selected or settings.app_env not in {"development", "test"}:
        parser.error("Select --migrate/--seed/--seed-admin in development/test only")
    if not settings.database_url or settings.auth_tenant_id != "demo_001":
        parser.error(
            "Configure DATABASE_URL for an isolated demo database and AUTH_TENANT_ID=demo_001"
        )
    if args.seed and not (
        settings.auth_demo_student_password and settings.auth_demo_sponsor_password
    ):
        parser.error("Configure both local demo passwords before seeding")
    if args.seed_admin and not settings.auth_demo_admin_password:
        parser.error("Configure AUTH_DEMO_ADMIN_PASSWORD before seeding the admin")
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
        if args.seed_admin:
            assert settings.auth_demo_admin_password
            provision_demo_admin(
                database,
                settings.auth_demo_admin_password.get_secret_value(),
                settings.app_env,
                settings.auth_tenant_id,
            )
    except (ValueError, OSError):
        raise SystemExit(
            "Demo setup failed; inspect local configuration without sharing credentials"
        ) from None


if __name__ == "__main__":
    main()
