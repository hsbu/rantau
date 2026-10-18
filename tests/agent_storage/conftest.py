from dataclasses import dataclass

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from backend.agent.migrations import migrate_agent_storage
from backend.agent.state import ConversationKey
from backend.authz.passwords import hash_password
from backend.authz.service import AuthService, LoginSession
from backend.authz.storage import Database
from tests.authz import conftest as auth_conftest

postgres_dsn = auth_conftest.postgres_dsn
PASSWORD = "isolated-agent-storage-password"


@pytest.fixture(scope="session")
def agent_dsn(postgres_dsn):
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute("DROP DATABASE IF EXISTS rantau_test_agent WITH (FORCE)")
        connection.execute("CREATE DATABASE rantau_test_agent")
    dsn = make_conninfo(postgres_dsn, dbname="rantau_test_agent")
    migrate_agent_storage(Database(dsn))
    return dsn


@pytest.fixture(scope="session")
def agent_password_hash():
    return hash_password(PASSWORD)


@dataclass
class Environment:
    database: Database
    auth: AuthService
    login: LoginSession

    def key(self, conversation="conversation_one", actor=None):
        actor = actor or self.login.actor
        return ConversationKey(
            tenant_id=actor.tenant_id,
            actor_id=actor.actor_id,
            session_id=actor.session_id,
            conversation_id=conversation,
        )


@pytest.fixture
def env(agent_dsn, agent_password_hash):
    database = Database(agent_dsn)
    with database.connection() as connection:
        connection.execute(
            "TRUNCATE agent_runs, agent_conversations, actors, auth_login_attempts, "
            "policy_decisions, demo_state CASCADE"
        )
        for tenant, actor, role, username in (
            ("demo_001", "stu_001", "STUDENT", "student"),
            ("demo_001", "stu_002", "STUDENT", "second"),
            ("demo_001", "par_001", "SPONSOR", "sponsor"),
            ("demo_other", "stu_001", "STUDENT", "student"),
        ):
            scopes = ["student:read", "payment:propose"] if role == "STUDENT" else ["sponsor:read"]
            connection.execute(
                "INSERT INTO actors (tenant_id, actor_id, role, scopes) VALUES (%s, %s, %s, %s)",
                (tenant, actor, role, scopes),
            )
            connection.execute(
                "INSERT INTO auth_credentials (tenant_id, actor_id, username, password_hash) "
                "VALUES (%s, %s, %s, %s)",
                (tenant, actor, username, agent_password_hash),
            )
        connection.execute(
            "INSERT INTO demo_state (tenant_id, scenario_id) VALUES ('demo_001', 'storage_test')"
        )
    auth = AuthService(database, "demo_001")
    return Environment(database, auth, auth.login("student", PASSWORD, "storage-test"))
