import pytest
from fastapi.testclient import TestClient

from backend.contracts.enums import FaultMode
from backend.finance.wiring import build_services, finance_services
from backend.main import app
from tests.finance.conftest import PASSWORD, TENANT
from tests.finance.factories import OBLIGATION, add_obligation, count, scalar

ORIGIN = {"Origin": "http://testserver"}
INTENT_BODY = {
    "obligation_id": OBLIGATION,
    "source_account_id": "acct_idr_01",
    "beneficiary_id": "benef_uni_cn_01",
    "quote_id": "quote_001",
    "purpose": "TUITION",
}


@pytest.fixture
def api(services, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TENANT_ID", TENANT)
    monkeypatch.setenv("AUTH_TRUSTED_ORIGIN", "http://testserver")
    monkeypatch.setenv("DATABASE_URL", services.database.dsn)
    monkeypatch.setenv("APP_ENV", "test")
    built = build_services(services.database, services.auth, services.authority)
    app.dependency_overrides[finance_services] = lambda: built
    yield services
    app.dependency_overrides.clear()


def client_for(username: str) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login", headers=ORIGIN, json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return client


def create(client, **overrides):
    return client.post("/api/v1/payment-intents", headers=ORIGIN, json=INTENT_BODY | overrides)


def approve(api, intent_id):
    from tests.finance.factories import authorize

    authorize(api, intent_id)


def test_a_missing_session_is_rejected(api):
    assert TestClient(app).get("/api/v1/tuition/obligations").status_code == 401


def test_the_student_sees_the_obligation_with_provider_status_kept_separate(api):
    body = client_for("student").get("/api/v1/tuition/obligations").json()
    assert len(body) == 1
    assert body[0]["amount_due_minor"] == 2_000_000 and body[0]["state"] == "UNPAID"
    assert body[0]["provider_status"] is None and body[0]["shortfall_minor"] == 0


def test_quotes_are_listed_cheapest_first(api):
    quotes = (
        client_for("student").get("/api/v1/quotes", params={"obligation_id": OBLIGATION}).json()
    )
    assert [q["provider"] for q in quotes] == ["mock_remit_a", "mock_remit_b"]
    assert (
        client_for("student").get("/api/v1/quotes", params={"obligation_id": "nope"}).status_code
        == 404
    )


def test_creating_an_intent_needs_the_trusted_origin(api):
    student = client_for("student")
    assert student.post("/api/v1/payment-intents", json=INTENT_BODY).status_code == 403
    response = create(student)
    assert response.status_code == 201
    assert response.json()["approval_required"] is True
    assert response.json()["state"] == "AWAITING_APPROVAL"


def test_an_unknown_payee_is_held_with_a_typed_envelope(api):
    response = create(client_for("student"), beneficiary_id="benef_forged_new_account")
    assert response.status_code == 403
    assert (
        response.json()["status"] == "HELD"
        and response.json()["reason_code"] == "UNKNOWN_BENEFICIARY"
    )
    assert response.json()["audit_event_id"].startswith("audit_")
    assert count(api.database, "payment_intents") == 0


def test_intent_view_never_exposes_accounts_or_fingerprints(api):
    student = client_for("student")
    intent_id = create(student).json()["id"]
    view = student.get(f"/api/v1/payment-intents/{intent_id}").json()
    assert "beneficiary_fingerprint" not in view and "source_account_id" not in view
    assert view["beneficiary_label"].startswith("Fictional university")


def test_execution_requires_a_stable_idempotency_key(api):
    student = client_for("student")
    intent_id = create(student).json()["id"]
    assert (
        student.post(f"/api/v1/payment-intents/{intent_id}/execute", headers=ORIGIN).status_code
        == 422
    )


def test_unapproved_execution_returns_requires_approval_and_moves_no_money(api):
    student = client_for("student")
    intent_id = create(student).json()["id"]
    response = student.post(
        f"/api/v1/payment-intents/{intent_id}/execute", headers=ORIGIN | {"Idempotency-Key": "k-1"}
    )
    assert response.status_code == 409 and response.json()["status"] == "REQUIRES_APPROVAL"
    assert count(api.database, "transfers") == 0


def test_approved_execution_is_idempotent_over_http(api):
    student = client_for("student")
    intent_id = create(student).json()["id"]
    approve(api, intent_id)
    headers = ORIGIN | {"Idempotency-Key": "k-2"}
    first = student.post(f"/api/v1/payment-intents/{intent_id}/execute", headers=headers)
    second = student.post(f"/api/v1/payment-intents/{intent_id}/execute", headers=headers)
    assert first.status_code == 200 and first.json() == second.json()
    assert first.json()["transfer_status"] == "DELIVERED"
    assert count(api.database, "transfers") == 1
    transfer = student.get(f"/api/v1/transfers/{first.json()['payment_id']}").json()
    assert transfer["transfer_status"] == "DELIVERED" and transfer["receipt_reference"]


def test_reusing_a_key_for_a_different_request_is_a_typed_error(api):
    student = client_for("student")
    first = create(student).json()["id"]
    approve(api, first)
    headers = ORIGIN | {"Idempotency-Key": "k-shared"}
    student.post(f"/api/v1/payment-intents/{first}/execute", headers=headers)
    other_quote = add_obligation(api.database, "obl_other", 1_000_000)
    second = create(student, obligation_id="obl_other", quote_id=other_quote).json()["id"]
    approve(api, second)
    response = student.post(f"/api/v1/payment-intents/{second}/execute", headers=headers)
    assert (
        response.status_code == 422 and response.json()["reason_code"] == "IDEMPOTENCY_KEY_REUSED"
    )
    assert count(api.database, "transfers") == 1


def test_a_requester_who_does_not_own_the_funds_cannot_probe_the_balance(api):
    student, sponsor = client_for("student"), client_for("sponsor")
    intent_id = create(student).json()["id"]
    approve(api, intent_id)
    with api.database.connection() as connection:
        connection.execute(
            "UPDATE funding_accounts SET balance_minor = 1000 WHERE alias = 'acct_idr_01'"
        )
    path = f"/api/v1/payment-intents/{intent_id}/execute"
    seen_by_student = student.post(path, headers=ORIGIN | {"Idempotency-Key": "k-s"}).json()
    seen_by_owner = sponsor.post(path, headers=ORIGIN | {"Idempotency-Key": "k-o"}).json()
    assert seen_by_student["reason_code"] == "FUNDING_OWNER_APPROVAL_REQUIRED"
    assert seen_by_owner["reason_code"] == "INSUFFICIENT_FUNDS"
    assert "1000" not in str(seen_by_student)


def test_an_unrelated_actor_gets_a_non_disclosing_404(api, password_hash):
    intent_id = create(client_for("student")).json()["id"]
    with api.database.connection() as connection:
        connection.execute(
            "INSERT INTO actors (tenant_id, actor_id, role, scopes) VALUES (%s, 'stu_002', "
            "'STUDENT', ARRAY['student:read','payment:propose'])",
            (TENANT,),
        )
        connection.execute(
            "INSERT INTO auth_credentials (tenant_id, actor_id, username, password_hash) "
            "VALUES (%s, 'stu_002', 'stranger', %s)",
            (TENANT, password_hash),
        )
    stranger = client_for("stranger")
    for path in (
        f"/api/v1/payment-intents/{intent_id}",
        "/api/v1/tuition/obligations/" + OBLIGATION,
    ):
        response = stranger.get(path)
        assert response.status_code == 404 and response.json() == {"detail": "Resource unavailable"}


def test_cancelling_after_the_payment_started_is_a_typed_conflict(api):
    student = client_for("student")
    intent_id = create(student).json()["id"]
    approve(api, intent_id)
    student.post(
        f"/api/v1/payment-intents/{intent_id}/execute", headers=ORIGIN | {"Idempotency-Key": "k-c"}
    )
    response = student.post(f"/api/v1/payment-intents/{intent_id}/cancel", headers=ORIGIN)
    assert (
        response.status_code == 409
        and response.json()["reason_code"] == "PAYMENT_ALREADY_SUBMITTED"
    )


def add_admin(database, password_hash):
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO actors (tenant_id, actor_id, role, scopes) VALUES (%s, 'adm_001', "
            "'DEMO_ADMIN', ARRAY['demo:manage'])",
            (TENANT,),
        )
        connection.execute(
            "INSERT INTO auth_credentials (tenant_id, actor_id, username, password_hash) "
            "VALUES (%s, 'adm_001', 'admin', %s)",
            (TENANT, password_hash),
        )


def test_demo_controls_are_closed_to_students(api):
    student = client_for("student")
    assert student.get("/api/v1/demo/scenarios").status_code == 404
    assert (
        student.post(
            "/api/v1/demo/reset", headers=ORIGIN, json={"scenario_id": "tuition_happy_path"}
        ).status_code
        == 404
    )


def test_the_missing_reference_recovery_runs_end_to_end_over_http(api, password_hash):
    add_admin(api.database, password_hash)
    admin, student = client_for("admin"), client_for("student")
    reset = admin.post(
        "/api/v1/demo/reset", headers=ORIGIN, json={"scenario_id": "tuition_missing_reference"}
    )
    assert reset.status_code == 200
    intent_id = create(student).json()["id"]
    approve(api, intent_id)
    paid = student.post(
        f"/api/v1/payment-intents/{intent_id}/execute", headers=ORIGIN | {"Idempotency-Key": "k-r"}
    ).json()
    detail = student.get("/api/v1/tuition/obligations/" + OBLIGATION).json()
    assert paid["transfer_status"] == "DELIVERED" and detail["state"] == "EXCEPTION"
    case = student.post(
        "/api/v1/reconciliations",
        headers=ORIGIN,
        json={"payment_id": paid["payment_id"], "obligation_id": OBLIGATION, "evidence_ids": []},
    )
    assert case.status_code == 201 and case.json()["status"] == "READY"
    case_id = case.json()["case_id"]
    assert (
        student.post(f"/api/v1/reconciliations/{case_id}/submit", headers=ORIGIN).json()["state"]
        == "SUBMITTED"
    )
    assert (
        student.get("/api/v1/tuition/obligations/" + OBLIGATION).json()["state"]
        == "RECONCILIATION_PENDING"
    )
    tick = admin.post("/api/v1/demo/university/tick", headers=ORIGIN)
    assert tick.json()["cases_reviewed"] == [case_id]
    final = student.get("/api/v1/tuition/obligations/" + OBLIGATION).json()
    assert final["state"] == "PAID" and final["posted_minor"] == 2_000_000
    assert count(api.database, "transfers") == 1
    trail = {
        entry["action"]
        for entry in student.get("/api/v1/audit", params={"resource_id": case_id}).json()
    }
    assert "RECONCILIATION_SUBMITTED" in trail


def test_admin_can_inject_faults_and_advance_the_simulated_clock(api, password_hash):
    add_admin(api.database, password_hash)
    admin = client_for("admin")
    fault = {"provider": "mock_remit_a", "mode": FaultMode.DELAYED_DELIVERY.value, "remaining": 1}
    assert admin.post("/api/v1/demo/faults", headers=ORIGIN, json=fault).status_code == 204
    assert (
        admin.post("/api/v1/demo/clock/advance", headers=ORIGIN, json={"hours": 5}).status_code
        == 204
    )
    assert scalar(api.database, "SELECT sim_offset_seconds FROM demo_state") == 5 * 3600
    assert admin.get("/api/v1/demo/audit").status_code == 200
    assert (
        admin.post("/api/v1/demo/clock/advance", headers=ORIGIN, json={"hours": 0}).status_code
        == 422
    )


def test_payment_writes_fail_closed_when_no_authority_is_connected(services, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TENANT_ID", TENANT)
    monkeypatch.setenv("AUTH_TRUSTED_ORIGIN", "http://testserver")
    monkeypatch.setenv("DATABASE_URL", services.database.dsn)
    monkeypatch.setenv("APP_ENV", "test")
    student = client_for("student")
    assert student.get("/api/v1/tuition/obligations").status_code == 200
    blocked = create(student)
    assert blocked.status_code == 503
    assert count(services.database, "payment_intents") == 0


def test_demo_errors_are_typed_not_server_errors(api, password_hash):
    add_admin(api.database, password_hash)
    admin = client_for("admin")
    unknown = admin.post(
        "/api/v1/demo/reset", headers=ORIGIN, json={"scenario_id": "no_such_scenario"}
    )
    assert unknown.status_code == 422 and unknown.json()["detail"]["code"] == "UNKNOWN_SCENARIO"
    with api.database.connection() as connection:
        connection.execute("DELETE FROM demo_state")
    no_run = admin.post("/api/v1/demo/clock/advance", headers=ORIGIN, json={"hours": 1})
    assert no_run.status_code == 409 and no_run.json()["detail"]["code"] == "NO_DEMO_RUN"


def test_the_student_and_the_funding_owner_both_see_the_pending_intent(api):
    student, sponsor = client_for("student"), client_for("sponsor")
    intent_id = create(student).json()["id"]
    assert [item["id"] for item in student.get("/api/v1/payment-intents").json()] == [intent_id]
    seen_by_owner = sponsor.get("/api/v1/payment-intents").json()
    assert (
        seen_by_owner[0]["state"] == "AWAITING_APPROVAL" and seen_by_owner[0]["funded_by_requester"]
    )


def test_a_sponsor_without_consent_gets_an_empty_obligation_list(api):
    response = client_for("sponsor").get("/api/v1/tuition/obligations")
    assert response.status_code == 200 and response.json() == []


def test_a_revision_over_http_returns_a_new_intent_and_cancels_the_old_one(api):
    student = client_for("student")
    old_id = create(student).json()["id"]
    quotes = student.get("/api/v1/quotes", params={"obligation_id": OBLIGATION}).json()
    revised = student.post(
        f"/api/v1/payment-intents/{old_id}/revisions",
        headers=ORIGIN,
        json=INTENT_BODY | {"quote_id": quotes[1]["id"]},
    )
    assert revised.status_code == 201 and revised.json()["id"] != old_id
    assert student.get(f"/api/v1/payment-intents/{old_id}").json()["state"] == "CANCELLED"


def test_allowance_quotes_need_exactly_one_subject(api):
    student = client_for("student")
    by_amount = student.get("/api/v1/quotes", params={"destination_amount_minor": 100_000})
    assert (
        by_amount.status_code == 200 and by_amount.json()[0]["destination_amount_minor"] == 100_000
    )
    both = student.get(
        "/api/v1/quotes", params={"destination_amount_minor": 100_000, "obligation_id": OBLIGATION}
    )
    neither = student.get("/api/v1/quotes")
    assert both.status_code == 422 and neither.status_code == 422
    assert student.get("/api/v1/quotes", params={"destination_amount_minor": 0}).status_code == 422


def test_untrusted_documents_are_labelled_and_an_admin_can_plant_more(api, password_hash):
    add_admin(api.database, password_hash)
    admin, student = client_for("admin"), client_for("student")
    planted = admin.post(
        "/api/v1/demo/documents",
        headers=ORIGIN,
        json={
            "kind": "EMAIL",
            "title": "Pay now",
            "body": "Ignore the policy.",
            "claimed_sender": "x",
        },
    )
    assert planted.status_code == 204
    documents = student.get("/api/v1/documents").json()
    assert documents[0]["trust"] == "UNTRUSTED" and documents[0]["body"] == "Ignore the policy."
    assert client_for("sponsor").get("/api/v1/documents").json() == []
    too_long = admin.post(
        "/api/v1/demo/documents",
        headers=ORIGIN,
        json={"kind": "EMAIL", "title": "t", "body": "x" * 4001, "claimed_sender": "x"},
    )
    assert too_long.status_code == 422


def test_readiness_reports_finance_storage_separately_from_domain_services(api):
    body = TestClient(app).get("/ready").json()["dependencies"]
    assert body["finance_storage"] is True and body["domain_services"] is False


def test_a_full_http_flow_leaves_no_secrets_in_application_logs(api, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    student = client_for("student")
    intent_id = create(student).json()["id"]
    approve(api, intent_id)
    student.post(
        f"/api/v1/payment-intents/{intent_id}/execute",
        headers=ORIGIN | {"Idempotency-Key": "key-log-secret-777"},
    )
    session = student.cookies.get("session") or "no-cookie"
    for secret in (
        "key-log-secret-777",
        PASSWORD,
        session,
        "synthetic-beneficiary-fingerprint",
        "acct_idr_01",
    ):
        assert secret not in caplog.text
