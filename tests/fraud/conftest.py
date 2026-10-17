"""Disposable SQL resource ownership adapter; never installed in application wiring."""

import pytest

from backend.contracts.enums import Role
from backend.contracts.models import ActorContext, ScopeDenied
from backend.fraud.security_cases import SecurityCaseService
from backend.fraud.security_store import SecurityStore
from tests.authz.conftest import database as database
from tests.authz.conftest import postgres_dsn as postgres_dsn


class SQLResourceAccess:
    def assert_access(self, connection, actor, resource_id):
        row = connection.execute(
            "SELECT owner_id FROM test_security_resources "
            "WHERE tenant_id = %s AND resource_id = %s FOR UPDATE",
            (actor.tenant_id, resource_id),
        ).fetchone()
        reviewer = actor.role == Role.DEMO_ADMIN and "security:review" in actor.scopes
        if row is None or (row["owner_id"] != actor.actor_id and not reviewer):
            raise ScopeDenied("Resource unavailable")


def actor(actor_id="stu_001", tenant="demo_001", role=Role.STUDENT, scopes=None):
    return ActorContext(
        actor_id=actor_id,
        tenant_id=tenant,
        session_id="session_" + actor_id,
        role=role,
        scopes=frozenset({"student:read", "payment:propose"} if scopes is None else scopes),
    )


@pytest.fixture
def security(database):
    with database.connection() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS test_security_resources "
            "(tenant_id text, resource_id text, owner_id text, "
            "PRIMARY KEY (tenant_id,resource_id))"
        )
        connection.execute("TRUNCATE test_security_resources")
        connection.execute(
            "INSERT INTO test_security_resources VALUES "
            "('demo_001','resource_001','stu_001'), "
            "('demo_001','resource_other','stu_other'), "
            "('demo_001','resource_sponsor','par_001'), "
            "('other_tenant','resource_001','stu_001')"
        )
    return SecurityCaseService(SecurityStore(SQLResourceAccess()))


@pytest.fixture
def student():
    return actor()


@pytest.fixture
def reviewer():
    return actor("reviewer_001", role=Role.DEMO_ADMIN, scopes={"security:review"})
