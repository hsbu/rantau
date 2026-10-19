"""Default HTTP wiring: real sessions, C reads and storage, mocked provider transport only."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from backend.agent.classifier import IntentClassification
from backend.agent.explanations import display_time
from backend.agent.migrations import migrate_agent_storage
from backend.agent.state import TuitionInput
from backend.contracts.enums import Intent
from backend.main import app
from tests.agent.test_openrouter_classifier import response_body
from tests.finance.conftest import PASSWORD, TENANT


@pytest.fixture
def runtime(services, monkeypatch):
    migrate_agent_storage(services.database)
    with services.database.connection() as connection:
        connection.execute("TRUNCATE agent_runs, agent_conversations, agent_actions")
    for name, value in {
        "AUTH_ENABLED": "true",
        "AUTH_TENANT_ID": TENANT,
        "AUTH_TRUSTED_ORIGIN": "http://testserver",
        "APP_ENV": "test",
        "DATABASE_URL": services.database.dsn,
        "OPENROUTER_API_KEY": "synthetic-runtime-key",
        "OPENROUTER_MODEL": "provider/configurable-runtime-model",
        "AGENT_WEB_RESEARCH_ENABLED": "false",
    }.items():
        monkeypatch.setenv(name, value)
    payloads, clients = [], []

    def handle(request):
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        payload = json.loads(request.content)
        payloads.append(payload)
        text = payload["messages"][1]["content"]
        classification = IntentClassification(
            intent=Intent.TUITION,
            needs_clarification=False,
            tuition=(
                TuitionInput(information_only=True)
                if "balance and deadline only" in text
                else TuitionInput(funding_owner="OTHER")
                if "sponsor account" in text
                else TuitionInput(funding_owner="SELF")
                if "own account" in text
                else TuitionInput()
            ),
        )
        return httpx.Response(200, json=response_body(classification.model_dump_json()))

    def sdk(**kwargs):
        client = AsyncOpenAI(
            **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
        )
        clients.append(client)
        return client

    monkeypatch.setattr("backend.agent.openrouter_classifier.AsyncOpenAI", sdk)
    assert not app.dependency_overrides
    return services, payloads, clients


def student_client(services):
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://testserver"},
        json={"username": "student", "password": PASSWORD},
    )
    assert response.status_code == 200
    return client


def message(client, text="Plan tuition", conversation="connected_chat"):
    return client.post(
        "/api/v1/agent/messages",
        headers={"Origin": "http://testserver"},
        json={
            "message": text,
            "conversation_id": conversation,
        },
    )


def test_default_chat_uses_real_reads_and_atomic_durable_memory(runtime, monkeypatch):
    services, payloads, clients = runtime
    with services.database.connection() as connection:
        balances = connection.execute(
            "SELECT alias, balance_minor FROM funding_accounts ORDER BY alias"
        ).fetchall()
    client = student_client(services)
    first = message(client, "Plan tuition private@example.org")
    assert first.status_code == 200, first.text
    assert "Which funding account" in first.json()["message"]
    with services.database.connection() as connection:
        due = connection.execute("SELECT due_at FROM tuition_obligations").fetchone()["due_at"]
    assert f"Due date: {display_time(due)}" in first.json()["message"]
    assert "Tuition remaining: CNY 20,000.00" in first.json()["message"]
    second = message(client, "Use my own account")
    assert second.status_code == 200, second.text
    assert "Selected:" in second.json()["message"]
    assert "No payment has been requested or executed" in second.json()["message"]
    assert "Prior intent: TUITION" in payloads[1]["messages"][1]["content"]
    assert "private@example.org" not in json.dumps(payloads)
    assert all(p["model"] == "provider/configurable-runtime-model" for p in payloads)
    with services.database.connection() as connection:
        draft = connection.execute("SELECT state, revision FROM agent_conversations").fetchone()
        assert draft["revision"] == 2
        assert draft["state"]["tuition"]["source_account_id"] == "acct_idr_stu_01"
        assert connection.execute("SELECT count(*) AS n FROM agent_runs").fetchone()["n"] == 2
        assert (
            connection.execute(
                "SELECT alias, balance_minor FROM funding_accounts ORDER BY alias"
            ).fetchall()
            == balances
        )
        for table in (
            "payment_intents",
            "transfers",
            "ledger_entries",
            "university_postings",
            "approvals",
            "reconciliation_cases",
        ):
            assert connection.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0
        raw = connection.execute("SELECT metadata FROM agent_runs").fetchall()
        assert "private@example.org" not in json.dumps(raw)
    # Historical diagnostics are independent of current model availability.
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    saved = client.get("/api/v1/agent/runs/" + second.json()["run_id"])
    assert saved.status_code == 200
    assert "Original chat text is not retained" in saved.json()["message"]
    assert len(payloads) == 2
    assert all(client.is_closed() for client in clients)


@pytest.mark.parametrize("with_preview", [False, True])
def test_balance_only_question_preserves_financial_records_and_existing_draft(
    runtime, with_preview
):
    from tests.finance.test_agent_details import domain

    services, _, _ = runtime
    client = student_client(services)
    if with_preview:
        assert message(client, "Plan tuition from my own account").status_code == 200
    before = domain(services.database)
    response = message(client, "Show my tuition balance and deadline only")
    assert response.status_code == 200
    body = response.json()
    assert "Tuition remaining: CNY 20,000.00" in body["message"]
    assert "University credited: CNY 0.00" in body["message"]
    assert "21 Nov 2026, 17:00 China time" in body["message"]
    assert "Which funding account" not in body["message"]
    assert "Selected:" not in body["message"]
    assert "confirm tuition" not in body["message"]
    assert [event["tool"] for event in body["tool_events"]] == ["get_tuition_obligation"]
    after = domain(services.database)
    for table in before.keys() - {"agent_conversations", "agent_runs"}:
        assert after[table] == before[table], table
    with services.database.connection() as connection:
        state = connection.execute("SELECT state FROM agent_conversations").fetchone()["state"]
        assert state["tuition"]["source_account_id"] == (
            "acct_idr_stu_01" if with_preview else None
        )
        assert bool(state["tuition"]["quote_id"]) == with_preview


@pytest.mark.parametrize("setting", ["OPENROUTER_API_KEY", "OPENROUTER_MODEL"])
def test_missing_model_configuration_fails_before_provider_or_storage_write(
    runtime, monkeypatch, setting
):
    services, payloads, _ = runtime
    monkeypatch.setenv(setting, "")
    response = message(student_client(services))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "CLASSIFIER_NOT_CONFIGURED"
    assert not payloads
    with services.database.connection() as connection:
        assert connection.execute("SELECT count(*) AS n FROM agent_runs").fetchone()["n"] == 0


def test_missing_agent_storage_fails_closed_without_auto_migration(runtime):
    services, payloads, _ = runtime
    client = student_client(services)
    with services.database.connection() as connection:
        connection.execute("ALTER TABLE agent_runs RENAME TO unavailable_agent_runs")
    try:
        response = message(client)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "AGENT_STORAGE_UNAVAILABLE"
        assert not payloads
    finally:
        with services.database.connection() as connection:
            connection.execute("ALTER TABLE unavailable_agent_runs RENAME TO agent_runs")


def test_sponsor_and_expired_session_cannot_send_or_read_another_run(runtime):
    services, payloads, _ = runtime
    client = student_client(services)
    result = message(client)
    assert result.status_code == 200
    run = "/api/v1/agent/runs/" + result.json()["run_id"]
    sponsor = TestClient(app)
    token = services.auth.login("sponsor", PASSWORD, "runtime-sponsor").token
    sponsor.cookies.set("session", token)
    assert message(sponsor).status_code == 404
    assert sponsor.get(run).status_code == 404
    assert len(payloads) == 1
    with services.database.connection() as connection:
        connection.execute("UPDATE auth_sessions SET expires_at = clock_timestamp()")
    assert message(client).status_code == 401
    assert client.get(run).status_code == 401
    assert len(payloads) == 1


def test_new_login_cannot_resume_or_read_the_previous_sessions_draft(runtime):
    services, payloads, _ = runtime
    first = student_client(services)
    result = message(first)
    assert result.status_code == 200
    second = student_client(services)
    assert second.get("/api/v1/agent/runs/" + result.json()["run_id"]).status_code == 404
    assert message(second).status_code == 200
    assert "Prior intent" not in payloads[1]["messages"][1]["content"]
    with services.database.connection() as connection:
        count = connection.execute("SELECT count(*) AS n FROM agent_conversations").fetchone()["n"]
        assert count == 2


def test_revocation_during_model_interpretation_prevents_reads_and_commit(runtime, monkeypatch):
    from backend.agent.openrouter_classifier import OpenRouterIntentClassifier

    services, payloads, clients = runtime
    original = OpenRouterIntentClassifier.classify

    async def revoke_after_model(classifier, text):
        result = await original(classifier, text)
        with services.database.connection() as connection:
            connection.execute("UPDATE auth_sessions SET revoked_at = clock_timestamp()")
        return result

    monkeypatch.setattr(OpenRouterIntentClassifier, "classify", revoke_after_model)
    response = message(student_client(services))
    assert response.status_code == 404
    assert len(payloads) == 1 and all(client.is_closed() for client in clients)
    with services.database.connection() as connection:
        for table in ("agent_conversations", "agent_runs", "payment_intents", "transfers"):
            assert connection.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0
