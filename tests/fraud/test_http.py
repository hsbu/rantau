"""Public case reads use real sessions, SQL cases and the actual finance adapter."""

import pytest
from fastapi.testclient import TestClient

from backend.authz.service import AuthService
from backend.fraud.finance_access import build_security_service
from backend.fraud.security_cases import SecurityReason
from backend.main import app
from tests.finance.conftest import PASSWORD, TENANT
from tests.finance.conftest import finance_db as finance_db
from tests.finance.conftest import finance_dsn as finance_dsn
from tests.finance.conftest import password_hash as password_hash
from tests.finance.conftest import seeded as seeded
from tests.finance.factories import proposal

ORIGIN = {"Origin": "http://testserver"}
FIELDS = {
    "case_id", "resource_id", "state", "reason", "created_at", "updated_at", "audit_event_id"
}


def client_for(username):
    client = TestClient(app)
    assert client.post(
        "/api/v1/auth/login", headers=ORIGIN, json={"username": username, "password": PASSWORD}
    ).status_code == 200
    return client


@pytest.fixture
def case_api(seeded, password_hash, monkeypatch):
    for key, value in {
        "AUTH_ENABLED": "true", "AUTH_TENANT_ID": TENANT,
        "AUTH_TRUSTED_ORIGIN": "http://testserver", "DATABASE_URL": seeded.dsn,
        "APP_ENV": "test",
    }.items():
        monkeypatch.setenv(key, value)
    with seeded.connection() as connection:
        connection.execute(
            "INSERT INTO actors (tenant_id,actor_id,role,scopes) VALUES "
            "('demo_001','stu_other','STUDENT',ARRAY['student:read']), "
            "('demo_001','reviewer','DEMO_ADMIN',ARRAY['security:review'])"
        )
        for actor, username in (
            ("stu_001", "student"), ("par_001", "sponsor"),
            ("stu_other", "stranger"), ("reviewer", "reviewer"),
        ):
            connection.execute(
                "INSERT INTO auth_credentials (tenant_id,actor_id,username,password_hash) "
                "VALUES (%s,%s,%s,%s)", (TENANT, actor, username, password_hash),
            )
    assert not app.dependency_overrides
    student = client_for("student")
    intent = student.post(
        "/api/v1/payment-intents", headers=ORIGIN, json=proposal().model_dump(mode="json")
    )
    assert intent.status_code == 201
    auth = AuthService(seeded, TENANT)
    actor = auth.authenticate(student.cookies.get("session"))
    with seeded.connection() as connection, connection.transaction():
        case = build_security_service(auth).create_case(
            connection, actor, intent.json()["id"], SecurityReason.PROMPT_INJECTION,
            ("private_evidence_alias",),
        )
    return seeded, student, case


@pytest.mark.parametrize("username", ["student", "sponsor", "reviewer"])
def test_related_sessions_receive_only_the_approved_public_fields(case_api, username):
    database, _, case = case_api
    response = client_for(username).get(f"/api/v1/security-cases/{case.case_id}")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == FIELDS
    assert body["case_id"] == case.case_id and body["resource_id"] == case.resource_id
    assert body["state"] == "OPEN" and body["reason"] == "PROMPT_INJECTION"
    assert "private_evidence_alias" not in response.text
    assert "stu_001" not in response.text
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) AS n FROM security_events").fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) AS n FROM transfers").fetchone()["n"] == 0


def test_strangers_and_missing_cases_have_identical_not_found_responses(case_api):
    _, _, case = case_api
    client = client_for("stranger")
    hidden = client.get(
        f"/api/v1/security-cases/{case.case_id}",
        headers={"X-Actor-ID": "stu_001", "X-Role": "DEMO_ADMIN", "X-Tenant-ID": TENANT},
    )
    missing = client.get("/api/v1/security-cases/case_unknown")
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json() == {"detail": "Resource unavailable"}
    assert hidden.headers["cache-control"] == missing.headers["cache-control"] == "no-store"


def test_missing_or_forged_session_cannot_read_a_case(case_api):
    _, _, case = case_api
    response = TestClient(app).get(
        f"/api/v1/security-cases/{case.case_id}",
        headers={"X-Actor-ID": "stu_001", "X-Role": "DEMO_ADMIN", "Cookie": "session=forged"},
    )
    assert response.status_code == 401


@pytest.mark.parametrize("change", ["scope", "revoked", "disabled", "expired", "credential"])
def test_current_session_and_read_scope_are_required_even_for_the_reporter(case_api, change):
    database, student, case = case_api
    with database.connection() as connection:
        if change == "scope":
            connection.execute("UPDATE actors SET scopes='{}' WHERE actor_id='stu_001'")
        elif change == "disabled":
            connection.execute("UPDATE actors SET active=false WHERE actor_id='stu_001'")
        elif change == "expired":
            connection.execute("UPDATE auth_sessions SET expires_at=clock_timestamp()")
        elif change == "credential":
            connection.execute(
                "UPDATE auth_credentials SET version=version+1 WHERE actor_id='stu_001'"
            )
        else:
            connection.execute("UPDATE auth_sessions SET revoked_at=clock_timestamp()")
    response = student.get(f"/api/v1/security-cases/{case.case_id}")
    assert response.status_code == (404 if change == "scope" else 401)
    assert "private_evidence_alias" not in response.text


def test_foreign_tenant_with_the_same_actor_alias_cannot_read_a_case(case_api, monkeypatch):
    database, _, case = case_api
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO actors (tenant_id,actor_id,role,scopes) "
            "VALUES ('foreign','stu_001','STUDENT',ARRAY['student:read'])"
        )
        connection.execute(
            "INSERT INTO auth_credentials (tenant_id,actor_id,username,password_hash) "
            "SELECT 'foreign',actor_id,username,password_hash FROM auth_credentials "
            "WHERE tenant_id='demo_001' AND actor_id='stu_001'"
        )
    monkeypatch.setenv("AUTH_TENANT_ID", "foreign")
    assert client_for("student").get(f"/api/v1/security-cases/{case.case_id}").status_code == 404


def test_storage_failures_are_sanitized_and_never_return_case_data(case_api):
    database, student, case = case_api
    with database.connection() as connection:
        connection.execute("ALTER TABLE security_cases RENAME TO unavailable_cases")
    try:
        response = student.get(f"/api/v1/security-cases/{case.case_id}")
        assert response.status_code == 503
        assert response.json() == {"detail": {"code": "SECURITY_CASE_UNAVAILABLE"}}
        assert response.headers["cache-control"] == "no-store"
    finally:
        with database.connection() as connection:
            connection.execute("ALTER TABLE unavailable_cases RENAME TO security_cases")


def test_a_session_revoked_after_initial_authentication_cannot_use_the_reporter_shortcut(
    case_api, monkeypatch
):
    database, student, case = case_api
    authenticate = AuthService.authenticate

    def revoke_after_auth(service, token):
        actor = authenticate(service, token)
        with database.connection() as connection:
            connection.execute(
                "UPDATE auth_sessions SET revoked_at=clock_timestamp() WHERE session_id=%s",
                (actor.session_id,),
            )
        return actor

    monkeypatch.setattr(AuthService, "authenticate", revoke_after_auth)
    response = student.get(f"/api/v1/security-cases/{case.case_id}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Resource unavailable"}


def test_malformed_identifiers_do_not_echo_input_and_no_mutation_route_is_exposed(case_api):
    _, student, case = case_api
    malformed = student.get("/api/v1/security-cases/private%20identifier")
    assert malformed.status_code == 422
    assert malformed.json() == {"detail": {"code": "INVALID_AUTH_REQUEST"}}
    assert student.post(f"/api/v1/security-cases/{case.case_id}", headers=ORIGIN).status_code == 405
    assert student.post("/api/v1/security-cases", headers=ORIGIN).status_code == 405


def test_case_lists_are_relationship_scoped_and_field_limited(case_api):
    database, student, case = case_api
    owned = student.get("/api/v1/security-cases")
    assert owned.status_code == 200, owned.text
    assert owned.headers["cache-control"] == "no-store"
    assert [item["case_id"] for item in owned.json()["cases"]] == [case.case_id]
    assert set(owned.json()["cases"][0]) == FIELDS
    assert "private_evidence_alias" not in owned.text and "stu_001" not in owned.text
    # A funding sponsor who did not open the case gets an empty page, not a leak.
    sponsor = client_for("sponsor").get("/api/v1/security-cases")
    assert sponsor.status_code == 200 and sponsor.json() == {"cases": []}
    # An unrelated student sees nothing from another actor's relationship scope.
    stranger = client_for("stranger").get("/api/v1/security-cases")
    assert stranger.status_code == 200 and stranger.json() == {"cases": []}
    # The reviewer scope sees the tenant page.
    reviewer = client_for("reviewer").get("/api/v1/security-cases")
    assert reviewer.status_code == 200
    assert [item["case_id"] for item in reviewer.json()["cases"]] == [case.case_id]
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) AS n FROM transfers").fetchone()["n"] == 0


def test_case_list_page_is_bounded_to_the_most_recent_cases(case_api):
    database, student, case = case_api
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO security_cases (tenant_id, case_id, resource_id, reason_code, state, "
            "opened_by, updated_at, audit_event_id) "
            "SELECT %s, 'case_bulk_' || g, 'intent_bulk_' || g, 'POLICY_REVIEW', 'OPEN', "
            "'stu_001', clock_timestamp() + (g || ' seconds')::interval, 'audit_bulk_' || g "
            "FROM generate_series(1, 150) g",
            (TENANT,),
        )
    body = student.get("/api/v1/security-cases").json()["cases"]
    assert len(body) == 100  # storage bound, never an unbounded page
    assert [item["case_id"] for item in body[:2]] == ["case_bulk_150", "case_bulk_149"]
    assert body[-1]["case_id"] == "case_bulk_51"
    assert case.case_id not in {item["case_id"] for item in body}


def test_case_list_requires_the_current_session_and_read_scope(case_api):
    database, student, _ = case_api
    assert student.get("/api/v1/security-cases").status_code == 200
    with database.connection() as connection:
        connection.execute("UPDATE actors SET scopes='{}' WHERE actor_id='stu_001'")
    denied = student.get("/api/v1/security-cases")
    assert denied.status_code == 404
    assert denied.json() == {"detail": "Resource unavailable"}
    assert denied.headers["cache-control"] == "no-store"


def test_a_foreign_tenant_alias_cannot_list_another_tenants_cases(case_api, monkeypatch):
    database, _, case = case_api
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO actors (tenant_id,actor_id,role,scopes) "
            "VALUES ('foreign','stu_001','STUDENT',ARRAY['student:read'])"
        )
        connection.execute(
            "INSERT INTO auth_credentials (tenant_id,actor_id,username,password_hash) "
            "SELECT 'foreign',actor_id,username,password_hash FROM auth_credentials "
            "WHERE tenant_id='demo_001' AND actor_id='stu_001'"
        )
    monkeypatch.setenv("AUTH_TENANT_ID", "foreign")
    response = client_for("student").get("/api/v1/security-cases")
    assert response.status_code == 200
    assert response.json() == {"cases": []}
    assert case.case_id not in response.text


def test_case_list_storage_failures_are_sanitized(case_api):
    database, student, _ = case_api
    with database.connection() as connection:
        connection.execute("ALTER TABLE security_cases RENAME TO unavailable_cases")
    try:
        response = student.get("/api/v1/security-cases")
        assert response.status_code == 503
        assert response.json() == {"detail": {"code": "SECURITY_CASE_UNAVAILABLE"}}
        assert response.headers["cache-control"] == "no-store"
    finally:
        with database.connection() as connection:
            connection.execute("ALTER TABLE unavailable_cases RENAME TO security_cases")


def test_the_endpoint_catalogue_exports_the_safe_list_contract():
    from backend.contracts.schema import contract_schema

    schema = contract_schema()
    operation = schema["paths"]["/api/v1/security-cases"]["get"]
    assert operation["x-owner"] == "B"
    assert operation["x-implementation"] == "implemented-requires-finance"
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SecurityCaseList"
    }
    definitions = schema["components"]["schemas"]
    assert set(definitions["SecurityCaseList"]["properties"]) == {"cases"}
    assert definitions["SecurityCaseList"]["properties"]["cases"]["items"] == {
        "$ref": "#/components/schemas/SecurityCaseView"
    }
    assert set(definitions["SecurityCaseView"]["properties"]) == FIELDS


def test_the_existing_endpoint_catalogue_exports_the_safe_response_contract():
    from backend.contracts.schema import contract_schema

    schema = contract_schema()
    operation = schema["paths"]["/api/v1/security-cases/{id}"]["get"]
    assert operation["x-owner"] == "B"
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SecurityCaseView"
    }
    assert set(schema["components"]["schemas"]["SecurityCaseView"]["properties"]) == FIELDS
