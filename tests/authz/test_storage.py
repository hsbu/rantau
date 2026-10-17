import pytest


def test_domain_identity_rows_keep_uuid_keys_and_tenant_scoped_aliases(service, signed_in):
    from datetime import UTC, datetime, timedelta
    from uuid import UUID

    service.grant_consent(
        signed_in.actor,
        "par_001",
        frozenset({"tuition_summary"}),
        datetime.now(UTC) + timedelta(hours=1),
    )
    with service.database.connection() as connection:
        rows = connection.execute("SELECT id FROM actors").fetchall()
        assert len(rows) == 2 and all(isinstance(row["id"], UUID) for row in rows)
        grant = connection.execute("SELECT id FROM student_sponsor_consents").fetchone()
        assert isinstance(grant["id"], UUID)
        connection.execute(
            "INSERT INTO actors (tenant_id, actor_id, role) "
            "VALUES ('other_tenant', 'stu_001', 'STUDENT')"
        )
        assert (
            connection.execute(
                "SELECT count(DISTINCT id) AS n FROM actors WHERE actor_id = 'stu_001'"
            ).fetchone()["n"]
            == 2
        )


def test_migration_checksum_is_portable_across_checkout_line_endings(database, monkeypatch):
    from pathlib import Path

    from backend.authz.storage import migrate

    original_read = Path.read_bytes

    def windows_bytes(path):
        return original_read(path).replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")

    monkeypatch.setattr(Path, "read_bytes", windows_bytes)
    migrate(database)


def test_readiness_checks_required_storage_not_only_migration_history(service):
    assert service.ready()
    with service.database.connection() as connection:
        connection.execute("DROP TABLE auth_sessions")
    try:
        assert not service.ready()
    finally:
        # Restore only this test's disposable database before the next fixture.
        with service.database.connection() as connection:
            connection.execute("DELETE FROM rantau_migrations WHERE version = '001_auth'")
            connection.execute(
                "DROP TABLE student_sponsor_consents, auth_credentials, "
                "actors, auth_login_attempts CASCADE"
            )


def test_migration_replays_verify_checksum_and_do_not_reseed(database):
    from backend.authz.storage import migrate

    migrate(database)
    with database.connection() as connection:
        connection.execute(
            "UPDATE rantau_migrations SET checksum = 'altered' WHERE version = '001_auth'"
        )
    with pytest.raises(ValueError, match="checksum"):
        migrate(database)
    with database.connection() as connection:
        # Restore the disposable test DB for subsequent tests, not application data.
        connection.execute(
            "DROP TABLE rantau_migrations, policy_decisions, "
            "approvals, mandates, authority_events, "
            "student_sponsor_consents, "
            "auth_sessions, auth_credentials, actors, auth_login_attempts CASCADE"
        )
        connection.execute("DROP FUNCTION protect_authority_history()")


def test_readiness_remains_503_with_auth_ready_and_domain_unwired(auth_client, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr("backend.main.database_available", AsyncMock(return_value=True))
    result = auth_client.get("/ready")
    assert result.status_code == 503
    assert result.json()["dependencies"]["authentication"] is True
    assert result.json()["dependencies"]["domain_services"] is False
