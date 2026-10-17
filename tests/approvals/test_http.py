from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.approvals.router import approval_service
from backend.config import Settings
from backend.contracts.schema import contract_schema
from backend.main import app
from tests.approvals.finance import snapshot_now
from tests.approvals.test_service import mandate_input

ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture
def api(authority, monkeypatch):
    for key, value in {
        "AUTH_ENABLED": "true",
        "AUTH_TENANT_ID": "demo_001",
        "APP_ENV": "test",
        "AUTH_TRUSTED_ORIGIN": "http://testserver",
        "DATABASE_URL": authority.auth.database.dsn,
    }.items():
        monkeypatch.setenv(key, value)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[approval_service] = lambda: authority
    with ExitStack() as stack:
        student = stack.enter_context(TestClient(app))
        sponsor = stack.enter_context(TestClient(app))
        for client, username, password in (
            (student, "student", "a-long-student-test-password"),
            (sponsor, "sponsor", "a-long-sponsor-test-password"),
        ):
            assert (
                client.post(
                    "/api/v1/auth/login",
                    headers=ORIGIN,
                    json={"username": username, "password": password},
                ).status_code
                == 200
            )
        try:
            yield student, sponsor
        finally:
            app.dependency_overrides = previous


def request(api):
    student, sponsor = api
    response = student.post("/api/v1/payment-intents/intent_001/approval-requests", headers=ORIGIN)
    assert response.status_code == 200
    view = sponsor.get("/api/v1/sponsor/approvals").json()[0]
    return response.json()["approval_id"], view


def test_separate_authenticated_sessions_review_and_approve(api):
    student, sponsor = api
    id, view = request(api)
    assert "source_account_id" not in view and "balance_minor" not in view
    assert view["simulated"] and "***" in view["source_label"]
    body = {"decision": "APPROVED", "terms_hash": view["terms_hash"]}
    assert (
        student.post(
            f"/api/v1/sponsor/approvals/{id}/decision", json=body, headers=ORIGIN
        ).status_code
        == 404
    )
    approved = sponsor.post(f"/api/v1/sponsor/approvals/{id}/decision", json=body, headers=ORIGIN)
    assert approved.status_code == 200 and approved.json()["decision"] == "APPROVED"
    assert approved.headers["cache-control"] == "no-store"
    assert (
        sponsor.post(
            f"/api/v1/sponsor/approvals/{id}/decision",
            json=body | {"decision": "REJECTED"},
            headers=ORIGIN,
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "change", [{"role": "SPONSOR"}, {"actor_id": "par_001"}, {"approved": True}]
)
def test_decision_body_cannot_inject_authority(api, change):
    _, sponsor = api
    id, view = request(api)
    response = sponsor.post(
        f"/api/v1/sponsor/approvals/{id}/decision",
        headers=ORIGIN,
        json={"decision": "APPROVED", "terms_hash": view["terms_hash"]} | change,
    )
    assert response.status_code == 422
    assert not any(field in response.text for field in change)


def test_origin_body_boundaries_and_private_ids(api):
    student, sponsor = api
    endpoint = "/api/v1/payment-intents/intent_001/approval-requests"
    assert student.post(endpoint).status_code == 403
    assert student.post(endpoint, headers=ORIGIN, json={"approved": True}).status_code == 422
    assert student.post(endpoint, headers=ORIGIN, content="x" * 4097).status_code == 413
    assert (
        sponsor.post(
            "/api/v1/sponsor/approvals/private/decision",
            headers=ORIGIN,
            json={"decision": "APPROVED", "terms_hash": "forged"},
        ).status_code
        == 404
    )
    assert student.get("/api/v1/sponsor/approvals").status_code == 404


def test_student_self_confirmation_is_own_account_only(api, authority):
    student, sponsor = api
    authority.finance.put(snapshot_now(own=True))
    assert (
        student.post(
            "/api/v1/payment-intents/intent_001/approval-requests", headers=ORIGIN
        ).status_code
        == 200
    )
    view = student.get("/api/v1/student/approvals").json()[0]
    url = f"/api/v1/student/approvals/{view['approval_id']}/decision"
    body = {"decision": "APPROVED", "terms_hash": view["terms_hash"]}
    assert sponsor.post(url, headers=ORIGIN, json=body).status_code == 404
    assert student.post(url, headers=ORIGIN, json=body).status_code == 200


def test_mandates_use_owner_session_and_revoke_without_deleting_history(api):
    student, sponsor = api
    body = mandate_input().model_dump(mode="json")
    url = "/api/v1/sponsor/mandates"
    assert student.post(url, json=body, headers=ORIGIN).status_code == 404
    created = sponsor.post(url, json=body, headers=ORIGIN)
    assert created.status_code == 200
    id = created.json()["id"]
    assert sponsor.put(f"{url}/{id}", json=body, headers=ORIGIN).json()["revision"] == 2
    assert sponsor.delete(f"{url}/{id}", headers=ORIGIN).status_code == 204
    assert sponsor.get(url).json()[0]["revoked"] is True


def test_fresh_student_session_without_read_scope_cannot_confirm(api, authority):
    student, _ = api
    authority.finance.put(snapshot_now(own=True))
    student.post("/api/v1/payment-intents/intent_001/approval-requests", headers=ORIGIN)
    view = student.get("/api/v1/student/approvals").json()[0]
    with authority.auth.database.connection() as connection:
        connection.execute(
            "UPDATE actors SET scopes=ARRAY['payment:propose','payment:execute'] "
            "WHERE actor_id='stu_001'"
        )
    response = student.post(
        f"/api/v1/student/approvals/{view['approval_id']}/decision",
        headers=ORIGIN,
        json={"decision": "APPROVED", "terms_hash": view["terms_hash"]},
    )
    assert response.status_code == 404


def test_runtime_without_finance_adapter_remains_unavailable(api):
    _, sponsor = api
    override = app.dependency_overrides.pop(approval_service)
    try:
        response = sponsor.get("/api/v1/sponsor/approvals")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "AUTHORITY_UNAVAILABLE"
    finally:
        app.dependency_overrides[approval_service] = override


@pytest.mark.parametrize("value", [0, -1, 3601])
def test_approval_ttl_is_bounded(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, approval_ttl_seconds=value)


def test_contract_catalogue_uses_safe_views_and_origin():
    paths = contract_schema()["paths"]
    get = paths["/api/v1/sponsor/approvals"]["get"]
    assert get["responses"]["200"]["content"]["application/json"]["schema"]["items"][
        "$ref"
    ].endswith("/ApprovalView")
    post = paths["/api/v1/sponsor/mandates"]["post"]
    assert post["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/MandateView"
    )
    assert any(header["name"] == "Origin" for header in post["parameters"])
