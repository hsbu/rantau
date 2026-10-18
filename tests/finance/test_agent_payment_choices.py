"""Read-only payment choices use real sessions, C linkage and durable ID-only state."""

import json

import pytest

from backend.demo.reset import reset_demo_fixture
from tests.finance.conftest import TENANT
from tests.finance.factories import add_obligation, proposal
from tests.finance.test_agent_recovery_security import delivered
from tests.finance.test_agent_recovery_security import recovery_runtime as recovery_runtime
from tests.finance.test_agent_runtime import message, student_client
from tests.finance.test_agent_runtime import runtime as runtime


def financial_snapshot(database):
    with database.connection() as c:
        result = {
            t: c.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]
            for t in (
                "payment_intents",
                "transfers",
                "ledger_entries",
                "spend_entries",
                "approvals",
                "university_postings",
                "reconciliation_cases",
                "security_holds",
                "security_cases",
            )
        }
        result["funds"] = c.execute(
            "SELECT alias,balance_minor FROM funding_accounts ORDER BY alias"
        ).fetchall()
    return result


def test_generic_tracking_lists_then_requires_explicit_selection_without_financial_effects(
    recovery_runtime,
):
    services, _, _ = recovery_runtime
    client, payment = delivered(recovery_runtime)
    before = financial_snapshot(services.database)
    listed = message(client, "Track my payment")
    assert listed.status_code == 200, listed.text
    assert "Payment 1:" in listed.json()["message"]
    assert "select payment 1" in listed.json()["message"]
    assert "acct_" not in listed.json()["message"] and "par_" not in listed.json()["message"]
    assert listed.json()["resources"] == []
    invalid = message(client, "select payment 2")
    assert invalid.status_code == 200
    assert "advertised payment number" in invalid.json()["message"]
    selected = message(client, "select payment 1")
    assert selected.status_code == 200, selected.text
    assert any(r["kind"] == "payment" and r["id"] == payment for r in selected.json()["resources"])
    assert financial_snapshot(services.database) == before
    with services.database.connection() as c:
        draft = c.execute("SELECT state FROM agent_conversations").fetchone()["state"]["recovery"]
        assert draft["payment_options"] == [payment] and draft["payment_id"] == payment
        raw = json.dumps(draft)
        assert "balance" not in raw and "APPROVED" not in raw and "account" not in raw
    assert "Reconciliation state: SUBMITTED" in message(client, "submit recovery").json()["message"]
    with services.database.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM reconciliation_cases").fetchone()["n"] == 1
        assert c.execute("SELECT count(*) AS n FROM spend_entries").fetchone()["n"] == 1
        assert c.execute("SELECT count(*) AS n FROM university_postings").fetchone()["n"] == 0


def test_exact_list_and_selection_do_not_need_model_credentials(recovery_runtime, monkeypatch):
    services, _, _ = recovery_runtime
    client, _ = delivered(recovery_runtime)
    before = financial_snapshot(services.database)
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("OPENROUTER_MODEL", "")
    assert "Payment 1:" in message(client, "list payments").json()["message"]
    selected = message(client, "select payment 1")
    assert selected.status_code == 200
    assert selected.json()["tool_events"][0]["tool"] == "select_student_payment"
    assert financial_snapshot(services.database) == before


@pytest.mark.parametrize("boundary", ["new_session", "new_conversation", "reset", "revoked"])
def test_advertised_options_do_not_cross_scope_or_scenario_boundaries(recovery_runtime, boundary):
    services, _, _ = recovery_runtime
    client, _ = delivered(recovery_runtime)
    assert message(client, "list payments").status_code == 200
    conversation = "connected_chat"
    if boundary == "new_session":
        client = student_client(services)
    elif boundary == "new_conversation":
        conversation = "another_conversation"
    elif boundary == "reset":
        reset_demo_fixture(services.database, TENANT, "tuition_happy_path")
    else:
        with services.database.connection() as c:
            c.execute("UPDATE auth_sessions SET revoked_at=clock_timestamp()")
    before = financial_snapshot(services.database)
    response = message(client, "select payment 1", conversation)
    assert response.status_code in {200, 401, 404}, response.text
    assert not any(
        e["tool"] == "select_student_payment" and e["status"] == "OK"
        for e in response.json().get("tool_events", [])
    )
    assert financial_snapshot(services.database) == before


@pytest.mark.parametrize("mode", ["unrelated_student", "mismatched_link"])
def test_listing_does_not_expose_unrelated_or_mislinked_payments(recovery_runtime, mode):
    services, _, _ = recovery_runtime
    client, payment = delivered(recovery_runtime)
    if mode == "mismatched_link":
        add_obligation(services.database, "obl_other", 2_000_000)
    with services.database.connection() as c:
        if mode == "unrelated_student":
            c.execute(
                "INSERT INTO actors (tenant_id,actor_id,role,scopes) "
                "VALUES (%s,'stu_other','STUDENT',ARRAY['student:read'])",
                (TENANT,),
            )
            c.execute("UPDATE tuition_obligations SET student_id='stu_other'")
        else:
            c.execute("UPDATE transfers SET obligation_alias='obl_other'")
    before = financial_snapshot(services.database)
    listed = message(client, "list payments")
    assert listed.status_code == 200
    assert "No eligible tuition payment" in listed.json()["message"]
    assert payment not in listed.text
    assert financial_snapshot(services.database) == before


def test_no_payments_is_a_truthful_read_only_result(recovery_runtime):
    services, _, _ = recovery_runtime
    before = financial_snapshot(services.database)
    response = message(student_client(services), "list payments")
    assert response.status_code == 200
    assert "No eligible tuition payment" in response.json()["message"]
    assert financial_snapshot(services.database) == before


def test_foreign_origin_cannot_list_or_select(recovery_runtime):
    from fastapi.testclient import TestClient

    from backend.main import app

    services, _, _ = recovery_runtime
    client = student_client(services)
    before = financial_snapshot(services.database)
    for text in ("list payments", "select payment 1"):
        response = client.post(
            "/api/v1/agent/messages",
            headers={"Origin": "https://evil.example"},
            json={"message": text, "conversation_id": "connected_chat"},
        )
        assert response.status_code == 403
        assert (
            TestClient(app)
            .post(
                "/api/v1/agent/messages",
                json={"message": text, "conversation_id": "connected_chat"},
            )
            .status_code
            == 401
        )
    assert financial_snapshot(services.database) == before


def test_numbered_choices_distinguish_two_payments_and_use_the_advertised_ids(recovery_runtime):
    services, _, _ = recovery_runtime
    client, first = delivered(recovery_runtime)
    quote = add_obligation(services.database, "obl_second", 1_000_000)
    origin = {"Origin": "http://testserver"}
    created = client.post(
        "/api/v1/payment-intents",
        headers=origin,
        json=proposal(
            obligation="obl_second",
            quote=quote,
            account="acct_idr_stu_01",
        ).model_dump(mode="json"),
    )
    assert created.status_code == 201, created.text
    intent = created.json()
    requested = client.post(
        f"/api/v1/payment-intents/{intent['id']}/approval-requests", headers=origin
    )
    assert requested.status_code == 200, requested.text
    decided = client.post(
        f"/api/v1/student/approvals/{requested.json()['approval_id']}/decision",
        headers=origin,
        json={"decision": "APPROVED", "terms_hash": intent["terms_hash"]},
    )
    assert decided.status_code == 200, decided.text
    executed = client.post(
        f"/api/v1/payment-intents/{intent['id']}/execute",
        headers=origin | {"Idempotency-Key": "setup-second-payment"},
    )
    assert executed.status_code == 200, executed.text
    second = executed.json()["payment_id"]
    before = financial_snapshot(services.database)
    listed = message(client, "list payments")
    assert "Payment 1:" in listed.json()["message"] and "Payment 2:" in listed.json()["message"]
    assert (
        "CNY 10,000.00" in listed.json()["message"] and "CNY 20,000.00" in listed.json()["message"]
    )
    with services.database.connection() as c:
        advertised = c.execute("SELECT state FROM agent_conversations").fetchone()["state"][
            "recovery"
        ]["payment_options"]
    assert set(advertised) == {first, second}
    selected = message(client, "select payment 2")
    assert selected.status_code == 200
    assert any(
        r["kind"] == "payment" and r["id"] == advertised[1] for r in selected.json()["resources"]
    )
    assert financial_snapshot(services.database) == before
