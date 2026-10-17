import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import psycopg
import pytest


@pytest.fixture(scope="session")
def postgres_dsn():
    configured = os.environ.get("RANTAU_TEST_DATABASE_URL")
    if configured:
        from psycopg.conninfo import conninfo_to_dict

        assert conninfo_to_dict(configured)["dbname"].startswith("rantau_test")
        yield configured
        return
    initdb, pg_ctl = shutil.which("initdb"), shutil.which("pg_ctl")
    if not initdb or not pg_ctl:
        pytest.fail(
            "Install PostgreSQL test binaries or set RANTAU_TEST_DATABASE_URL to rantau_test*"
        )
    scratch = Path(".generated")
    scratch.mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="auth-postgres-", dir=scratch)).resolve()
    data = directory / "data"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    def run(*args):
        # A Windows PostgreSQL child can inherit PIPE handles after pg_ctl exits.
        # Files keep communicate() from waiting for a running server to close them.
        with (directory / "commands.log").open("ab") as output:
            result = subprocess.run(
                args, stdout=output, stderr=output, timeout=60, creationflags=creationflags
            )
        assert result.returncode == 0, (directory / "commands.log").read_text(errors="replace")

    run(initdb, "-D", str(data), "-U", "postgres", "-A", "trust", "-E", "UTF8", "--locale=C")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    run(
        pg_ctl,
        "-D",
        str(data),
        "-l",
        str(directory / "server.log"),
        "-o",
        f"-h 127.0.0.1 -p {port} -F",
        "-w",
        "start",
    )
    try:
        yield f"host=127.0.0.1 port={port} user=postgres dbname=postgres"
    finally:
        run(pg_ctl, "-D", str(data), "-m", "fast", "-w", "stop")


@pytest.fixture
def database(postgres_dsn):
    from backend.authz.storage import Database, migrate

    database = Database(postgres_dsn)
    migrate(database)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "TRUNCATE actors, auth_login_attempts, policy_decisions, approvals, mandates, "
            "authority_events, security_holds, security_cases, security_events CASCADE"
        )
    return database


@pytest.fixture(scope="session")
def password_hashes():
    from backend.authz.passwords import hash_password

    return hash_password("a-long-student-test-password"), hash_password(
        "a-long-sponsor-test-password"
    )


@pytest.fixture
def service(database, password_hashes):
    from backend.authz.service import AuthService

    # Fixed synthetic records, using real salted hashes calculated once per test session.
    # Bootstrap itself is exercised separately; most tests exercise session/access behavior.
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO actors (tenant_id, actor_id, role, scopes) VALUES "
            "('demo_001', 'stu_001', 'STUDENT', ARRAY['student:read','payment:propose']), "
            "('demo_001', 'par_001', 'SPONSOR', ARRAY['sponsor:read','sponsor:approve'])"
        )
        for actor_id, username, password_hash in (
            ("stu_001", "student", password_hashes[0]),
            ("par_001", "sponsor", password_hashes[1]),
        ):
            connection.execute(
                "INSERT INTO auth_credentials (tenant_id, actor_id, username, password_hash) "
                "VALUES ('demo_001', %s, %s, %s)",
                (actor_id, username, password_hash),
            )
    return AuthService(database, "demo_001")


@pytest.fixture
def signed_in(service):
    return service.login("student", "a-long-student-test-password", "test-client")


@pytest.fixture
def auth_client(service, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app

    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TENANT_ID", "demo_001")
    monkeypatch.setenv("AUTH_TRUSTED_ORIGIN", "http://testserver")
    monkeypatch.setenv("DATABASE_URL", service.database.dsn)
    monkeypatch.setenv("APP_ENV", "test")
    with TestClient(app) as client:
        yield client
