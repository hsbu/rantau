import pytest

from backend.authz.bootstrap import ADMIN_SCOPES, provision_demo_admin
from backend.contracts.enums import Role

ADMIN_PASSWORD = "a-long-admin-test-password"


def rows(database, sql, params=()):
    with database.connection() as connection:
        return connection.execute(sql, params).fetchall()


def test_the_admin_can_sign_in_with_a_dedicated_least_privilege_role(service):
    provision_demo_admin(service.database, ADMIN_PASSWORD, "test")
    session = service.login("admin", ADMIN_PASSWORD, "admin-tests")
    assert session.actor.role == Role.DEMO_ADMIN
    assert session.actor.scopes == frozenset(ADMIN_SCOPES) == frozenset({"demo:manage"})


def test_the_admin_holds_no_payment_approval_or_hold_review_authority(service):
    provision_demo_admin(service.database, ADMIN_PASSWORD, "test")
    scopes = service.login("admin", ADMIN_PASSWORD, "admin-tests").actor.scopes
    forbidden = {"payment:execute", "payment:propose", "sponsor:approve", "security:review"}
    assert not scopes & forbidden


def test_adding_the_admin_changes_no_existing_identity(service):
    before = rows(service.database, "SELECT actor_id, role, scopes FROM actors ORDER BY actor_id")
    hashes = rows(
        service.database, "SELECT actor_id, password_hash FROM auth_credentials ORDER BY 1"
    )
    provision_demo_admin(service.database, ADMIN_PASSWORD, "test")
    after = rows(service.database, "SELECT actor_id, role, scopes FROM actors ORDER BY actor_id")
    assert [row for row in after if row["actor_id"] != "adm_001"] == before
    kept = rows(
        service.database,
        "SELECT actor_id, password_hash FROM auth_credentials "
        "WHERE actor_id <> 'adm_001' ORDER BY 1",
    )
    assert kept == hashes


def test_an_existing_admin_is_never_overwritten(service):
    provision_demo_admin(service.database, ADMIN_PASSWORD, "test")
    original = rows(
        service.database, "SELECT password_hash FROM auth_credentials WHERE actor_id = 'adm_001'"
    )
    with pytest.raises(ValueError, match="already exists"):
        provision_demo_admin(service.database, "another-long-password-1", "test")
    assert (
        rows(
            service.database,
            "SELECT password_hash FROM auth_credentials WHERE actor_id = 'adm_001'",
        )
        == original
    )


def test_the_admin_is_refused_outside_development_and_with_a_weak_password(service):
    with pytest.raises(ValueError, match="development/test"):
        provision_demo_admin(service.database, ADMIN_PASSWORD, "production")
    with pytest.raises(ValueError, match="12-128"):
        provision_demo_admin(service.database, "short", "test")
    assert rows(service.database, "SELECT 1 FROM actors WHERE actor_id = 'adm_001'") == []
