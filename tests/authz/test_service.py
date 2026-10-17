from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest


def test_passwords_are_salted_and_fail_closed_on_malformed_hash():
    from backend.authz.passwords import hash_password, verify_password

    first = hash_password("a-long-student-test-password")
    second = hash_password("a-long-student-test-password")
    assert first != second
    assert "a-long-student" not in first
    assert verify_password("a-long-student-test-password", first)
    assert not verify_password("wrong-password", first)
    for malformed in ("", "scrypt$invalid", first + "junk"):
        assert not verify_password("a-long-student-test-password", malformed)
    with pytest.raises(ValueError):
        hash_password("short")


def test_separate_sessions_are_persistent_and_store_only_token_digests(service):
    from backend.authz.service import AuthService

    student = service.login("student", "a-long-student-test-password", "test-client")
    sponsor = service.login("sponsor", "a-long-sponsor-test-password", "test-client")
    assert student.token != sponsor.token
    assert student.actor.actor_id == "stu_001"
    assert sponsor.actor.role == "SPONSOR"
    assert "sponsor:approve" not in student.actor.scopes
    assert student.token not in repr(student)
    restarted = AuthService(service.database, "demo_001")
    assert restarted.authenticate(student.token) == student.actor
    with service.database.connection() as connection:
        rows = connection.execute(
            "SELECT token_digest, expires_at, created_at FROM auth_sessions"
        ).fetchall()
    assert len(rows) == 2
    assert all(row["token_digest"] not in (student.token, sponsor.token) for row in rows)
    assert all((row["expires_at"] - row["created_at"]).total_seconds() == 3600 for row in rows)


@pytest.mark.parametrize("change", ["expiry", "revocation", "disabled", "credential_change"])
def test_expired_revoked_disabled_or_changed_credentials_reject_sessions(
    service, signed_in, change
):
    from backend.authz.service import InvalidSession

    with service.database.connection() as connection:
        if change == "expiry":
            connection.execute("UPDATE auth_sessions SET expires_at = now() - interval '1 second'")
        elif change == "revocation":
            service.logout(signed_in.token)
        elif change == "disabled":
            connection.execute("UPDATE actors SET active = false WHERE actor_id = 'stu_001'")
        else:
            connection.execute("UPDATE auth_credentials SET version = version + 1")
    with pytest.raises(InvalidSession):
        service.authenticate(signed_in.token)


@pytest.mark.parametrize(
    "token", [None, "", "forged", "x" * 10000], ids=["missing", "empty", "forged", "oversized"]
)
def test_missing_or_malformed_tokens_are_unauthenticated(service, token):
    from backend.authz.service import InvalidSession

    with pytest.raises(InvalidSession):
        service.authenticate(token)


def test_login_rejects_wrong_credentials_and_tenant_confusion(service):
    from backend.authz.service import AuthService, InvalidSession

    for username in ("student", "missing"):
        with pytest.raises(InvalidSession):
            service.login(username, "wrong-password", "test-client")
    session = service.login("student", "a-long-student-test-password", "test-client")
    with pytest.raises(InvalidSession):
        AuthService(service.database, "other_tenant").authenticate(session.token)
    assert service.authenticate(session.token).actor_id == "stu_001"


def test_attempt_limits_are_atomic_across_service_instances(service):
    from backend.authz.service import AuthService, InvalidSession, LoginThrottled

    def attempt(index):
        instance = AuthService(service.database, "demo_001")
        try:
            instance.login("student", "wrong-password", f"client-{index}")
        except LoginThrottled:
            return "limited"
        except InvalidSession:
            return "invalid"

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert results.count("invalid") == 5
    assert results.count("limited") == 1
    with service.database.connection() as connection:
        connection.execute(
            "UPDATE auth_login_attempts SET window_started = now() - interval '16 minutes'"
        )
    assert (
        service.login("student", "a-long-student-test-password", "new-client").actor.actor_id
        == "stu_001"
    )


def test_client_limit_blocks_username_rotation(service):
    from backend.authz.service import InvalidSession, LoginThrottled

    for index in range(30):
        with pytest.raises(InvalidSession):
            service.login(f"unknown-{index}", "wrong-password", "same-client")
    with pytest.raises(LoginThrottled):
        service.login("student", "a-long-student-test-password", "same-client")


def test_bootstrap_cannot_run_in_production_or_overwrite_existing_identities(database):
    from backend.authz.bootstrap import provision_demo

    with pytest.raises(ValueError):
        provision_demo(database, "student-test-password", "sponsor-test-password", "production")
    with pytest.raises(ValueError):
        provision_demo(database, "shared-test-password", "shared-test-password", "test")
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) AS n FROM actors").fetchone()["n"] == 0
    provision_demo(database, "student-test-password", "sponsor-test-password", "test")
    with pytest.raises(ValueError):
        provision_demo(database, "new-student-password", "new-sponsor-password", "test")
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) AS n FROM actors").fetchone()["n"] == 2


def test_consent_is_field_limited_expiring_and_revocable(service, signed_in):
    from backend.authz.access import AccessPolicy
    from backend.contracts.models import ScopeDenied

    sponsor = service.login("sponsor", "a-long-sponsor-test-password", "test-client").actor
    access = AccessPolicy(service)
    with pytest.raises(ScopeDenied):
        access.require_student_fields(
            sponsor, "demo_001", "stu_001", frozenset({"tuition_summary"})
        )
    expiry = datetime.now(UTC) + timedelta(hours=1)
    service.grant_consent(signed_in.actor, "par_001", frozenset({"tuition_summary"}), expiry)
    access.require_student_fields(sponsor, "demo_001", "stu_001", frozenset({"tuition_summary"}))
    with pytest.raises(ScopeDenied):
        access.require_student_fields(sponsor, "demo_001", "stu_001", frozenset({"case_summary"}))
    service.revoke_consent(signed_in.actor, "par_001")
    with pytest.raises(ScopeDenied):
        access.require_student_fields(
            sponsor, "demo_001", "stu_001", frozenset({"tuition_summary"})
        )
    service.grant_consent(signed_in.actor, "par_001", frozenset({"tuition_summary"}), expiry)
    with service.database.connection() as connection:
        connection.execute(
            "UPDATE student_sponsor_consents SET expires_at = now() - interval '1 second'"
        )
    with pytest.raises(ScopeDenied):
        access.require_student_fields(
            sponsor, "demo_001", "stu_001", frozenset({"tuition_summary"})
        )


def test_access_rechecks_current_actor_and_never_promotes_student(service, signed_in):
    from backend.authz.access import AccessPolicy
    from backend.contracts.models import ScopeDenied

    access = AccessPolicy(service)
    access.require_owner(signed_in.actor, "demo_001", "stu_001")
    with pytest.raises(ScopeDenied):
        access.require_sponsor(signed_in.actor, "demo_001", "stu_001")
    with pytest.raises(ScopeDenied):
        access.require_owner(signed_in.actor, "other_tenant", "stu_001")
    with pytest.raises(ScopeDenied):
        access.require_owner(signed_in.actor, "demo_001", "par_001")
    service.logout(signed_in.token)
    with pytest.raises(ScopeDenied):
        access.require_owner(signed_in.actor, "demo_001", "stu_001")


def test_consent_cannot_target_other_tenants_roles_or_add_authority(service, signed_in):
    from backend.contracts.models import ScopeDenied

    expiry = datetime.now(UTC) + timedelta(hours=1)
    with service.database.connection() as connection:
        connection.execute(
            "INSERT INTO actors (tenant_id, actor_id, role, scopes) "
            "VALUES ('foreign', 'par_foreign', 'SPONSOR', '{}')"
        )
    for sponsor_id in ("par_foreign", "stu_001", "unknown"):
        with pytest.raises(ScopeDenied):
            service.grant_consent(
                signed_in.actor, sponsor_id, frozenset({"tuition_summary"}), expiry
            )
    for fields in (frozenset(), frozenset({"payment:execute"})):
        with pytest.raises(ValueError):
            service.grant_consent(signed_in.actor, "par_001", fields, expiry)
    with pytest.raises(ValueError):
        service.grant_consent(
            signed_in.actor,
            "par_001",
            frozenset({"tuition_summary"}),
            datetime.now(UTC) - timedelta(seconds=1),
        )


@pytest.mark.parametrize("who", ["student", "sponsor"])
def test_fresh_auth_after_read_scope_removal_does_not_disclose_student_fields(
    service, signed_in, who
):
    from backend.authz.access import AccessPolicy
    from backend.contracts.models import ScopeDenied

    sponsor = service.login("sponsor", "a-long-sponsor-test-password", "test-client")
    service.grant_consent(
        signed_in.actor,
        "par_001",
        frozenset({"tuition_summary"}),
        datetime.now(UTC) + timedelta(hours=1),
    )
    target = signed_in if who == "student" else sponsor
    with service.database.connection() as connection:
        connection.execute(
            "UPDATE actors SET scopes = '{}' WHERE actor_id = %s", (target.actor.actor_id,)
        )
    current = service.authenticate(target.token)
    with pytest.raises(ScopeDenied):
        AccessPolicy(service).require_student_fields(
            current, "demo_001", "stu_001", frozenset({"tuition_summary"})
        )
    if who == "student":
        with pytest.raises(ScopeDenied):
            service.grant_consent(
                current,
                "par_001",
                frozenset({"tuition_summary"}),
                datetime.now(UTC) + timedelta(hours=1),
            )
