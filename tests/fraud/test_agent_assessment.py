"""Default Chat wiring uses B advisory assessment with real sessions and SQL state."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from backend.agent.classifier import IntentClassification
from backend.agent.migrations import migrate_agent_storage
from backend.contracts.enums import Intent
from backend.contracts.models import ScopeDenied
from backend.demo.reset import reset_demo_fixture
from backend.demo.scenarios import FORGED_EMAIL, FORGED_INVOICE
from backend.fraud.assessment import FraudAssessor
from backend.fraud.finance_access import build_security_service
from backend.fraud.models import SemanticFraudSignals
from backend.fraud.security_cases import SecurityReason
from backend.main import app
from tests.agent.test_openrouter_classifier import response_body
from tests.finance.conftest import PASSWORD, TENANT
from tests.finance.conftest import finance_db as finance_db
from tests.finance.conftest import finance_dsn as finance_dsn
from tests.finance.conftest import password_hash as password_hash
from tests.finance.conftest import seeded as seeded
from tests.finance.conftest import services as services
from tests.finance.factories import proposal

ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture
def assessment_runtime(services, monkeypatch):
    database = services.database
    migrate_agent_storage(database)
    with database.connection() as connection:
        connection.execute("TRUNCATE agent_runs, agent_conversations")
    for name, value in {
        "AUTH_ENABLED": "true",
        "AUTH_TENANT_ID": TENANT,
        "AUTH_TRUSTED_ORIGIN": "http://testserver",
        "APP_ENV": "test",
        "DATABASE_URL": database.dsn,
        "OPENROUTER_API_KEY": "synthetic-assessment-key",
        "OPENROUTER_MODEL": "provider/assessment-fixture",
    }.items():
        monkeypatch.setenv(name, value)
    state = {
        "payloads": [], "clients": [], "revoke": False, "unavailable": False,
        "semantic_output": '{"indicators":["URGENCY"]}',
    }

    def handle(request):
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        payload = json.loads(request.content)
        state["payloads"].append(payload)
        schema = payload["response_format"]["json_schema"]["name"]
        if schema == "intent_classification":
            content = IntentClassification(
                intent=Intent.VERIFY_MESSAGE, needs_clarification=False
            ).model_dump_json()
        else:
            assert schema == "fraud_signals"
            if state["revoke"]:
                with database.connection() as connection:
                    connection.execute("UPDATE auth_sessions SET revoked_at = clock_timestamp()")
            if state["unavailable"]:
                return httpx.Response(503, json={"error": "synthetic provider unavailable"})
            content = state["semantic_output"]
        return httpx.Response(200, json=response_body(content))

    def sdk(**kwargs):
        kwargs["max_retries"] = 0
        client = AsyncOpenAI(
            **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
        )
        state["clients"].append(client)
        return client

    monkeypatch.setattr("backend.agent.openrouter_classifier.AsyncOpenAI", sdk)
    monkeypatch.setattr("backend.fraud.assessment.AsyncOpenAI", sdk)
    assert not app.dependency_overrides
    return services, state


def sign_in(username="student"):
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login", headers=ORIGIN,
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return client


def assess(client, text):
    return client.post(
        "/api/v1/agent/messages",
        headers=ORIGIN,
        json={"message": text, "conversation_id": "fraud_boundary"},
    )


def financial_state(database):
    with database.connection() as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
            for table in (
                "funding_accounts", "beneficiaries", "payment_intents", "transfers",
                "ledger_entries", "university_postings", "approvals", "mandates",
                "security_holds", "security_cases", "security_events",
            )
        }


@pytest.mark.parametrize(
    "text", [FORGED_INVOICE.body, FORGED_EMAIL.body, "Please assess this message."]
)
def test_message_gets_advisory_assessment_without_financial_effects(
    assessment_runtime, text
):
    services, state = assessment_runtime
    client = sign_in()
    before = financial_state(services.database)
    response = assess(client, text + " private@example.org session_private 123456789012")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["requested_action"] == "VERIFY_MESSAGE"
    assert any(
        event["tool"] == "assess_fraud_risk" and event["status"] == "OK"
        for event in body["tool_events"]
    )
    assert "REVIEW_REQUIRED" in body["message"]
    assert len(state["payloads"]) == 2
    assert {p["response_format"]["json_schema"]["name"] for p in state["payloads"]} == {
        "intent_classification", "fraud_signals",
    }
    assert "private@example.org" not in json.dumps(state["payloads"])
    assert "session_private" not in json.dumps(state["payloads"])
    assert "123456789012" not in json.dumps(state["payloads"])
    assert financial_state(services.database) == before
    with services.database.connection() as connection:
        rows = connection.execute("SELECT metadata FROM agent_runs").fetchall()
        assert len(rows) == 1
        assert text not in json.dumps(rows)
        assert "private@example.org" not in json.dumps(rows)
    assert all(client.is_closed() for client in state["clients"])


def test_assessment_cannot_clear_an_existing_payment_hold(assessment_runtime):
    services, state = assessment_runtime
    reset_demo_fixture(services.database, TENANT, "forged_beneficiary")
    client = sign_in()
    refused = client.post(
        "/api/v1/payment-intents", headers=ORIGIN,
        json=proposal(beneficiary="benef_unverified_01").model_dump(mode="json"),
    )
    assert refused.status_code == 403, refused.text
    actor = services.auth.authenticate(client.cookies.get("session"))
    with services.database.connection() as connection, connection.transaction():
        build_security_service(services.auth).place_hold(
            connection, actor, refused.json()["resource_id"], SecurityReason.PROMPT_INJECTION
        )
    before = financial_state(services.database)
    assert before["security_holds"]
    response = assess(client, FORGED_EMAIL.body)
    assert response.status_code == 200, response.text
    assert any(event["status"] == "OK" for event in response.json()["tool_events"])
    assert len(state["payloads"]) == 2
    assert financial_state(services.database) == before


def test_fraud_provider_failure_keeps_local_advisory_assessment(assessment_runtime):
    services, state = assessment_runtime
    state["unavailable"] = True
    before = financial_state(services.database)
    response = assess(sign_in(), FORGED_INVOICE.body)
    assert response.status_code == 200, response.text
    assert "REVIEW_REQUIRED" in response.json()["message"]
    assert any(event["status"] == "OK" for event in response.json()["tool_events"])
    assert len(state["payloads"]) == 2
    assert financial_state(services.database) == before
    assert all(client.is_closed() for client in state["clients"])


def test_model_authority_fields_are_rejected_without_financial_effects(assessment_runtime):
    services, state = assessment_runtime
    state["semantic_output"] = (
        '{"indicators":[],"next_action":"ALLOW","beneficiary_verified":true}'
    )
    before = financial_state(services.database)
    response = assess(sign_in(), "Please check this message.")
    assert response.status_code == 200, response.text
    assert "VERIFY_WITH_TRUSTED_SOURCE" in response.json()["message"]
    assert len(state["payloads"]) == 2
    assert financial_state(services.database) == before
    assert all(client.is_closed() for client in state["clients"])


def test_revocation_during_fraud_assessment_discards_result_and_run(assessment_runtime):
    services, state = assessment_runtime
    state["revoke"] = True
    before = financial_state(services.database)
    response = assess(sign_in(), FORGED_EMAIL.body)
    assert response.status_code == 404, response.text
    assert len(state["payloads"]) == 2
    with services.database.connection() as connection:
        for table in ("agent_runs", "agent_conversations"):
            assert connection.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0
    assert financial_state(services.database) == before
    assert all(client.is_closed() for client in state["clients"])


def test_sponsor_cannot_invoke_student_assessment(assessment_runtime):
    services, state = assessment_runtime
    before = financial_state(services.database)
    response = assess(sign_in("sponsor"), FORGED_EMAIL.body)
    assert response.status_code == 404
    assert state["payloads"] == []
    assert financial_state(services.database) == before


def security_port(services, assessor):
    from backend.finance.ports import FinanceAgentReadPort
    from backend.finance.reads import FinanceReads
    from backend.fraud.agent_port import SecurityAgentReadPort
    from backend.university.port import ObligationReader

    obligations = ObligationReader(services.database, services.auth)
    delegate = FinanceAgentReadPort(
        FinanceReads(services.database, services.auth, obligations), obligations
    )
    return SecurityAgentReadPort(delegate, services.auth, assessor)


async def test_adapter_rechecks_session_after_classification_without_a_graph(services):
    actor = services.actor("stu_001")

    class RevokingClassifier:
        async def classify(self, message):
            with services.database.connection() as connection:
                connection.execute("UPDATE auth_sessions SET revoked_at = clock_timestamp()")
            return SemanticFraudSignals(indicators=())

    port = security_port(services, FraudAssessor(RevokingClassifier()))
    with pytest.raises(ScopeDenied):
        await port.assess_message(FORGED_EMAIL.body, actor)


@pytest.mark.parametrize("claim", ["revoked", "tenant", "scope", "sponsor"])
async def test_adapter_denies_invalid_authority_before_classification(services, claim):
    actor = services.actor("par_001" if claim == "sponsor" else "stu_001")
    if claim == "revoked":
        with services.database.connection() as connection:
            connection.execute("UPDATE auth_sessions SET revoked_at = clock_timestamp()")
    elif claim == "tenant":
        actor = actor.model_copy(update={"tenant_id": "other_tenant"})
    elif claim == "scope":
        with services.database.connection() as connection:
            connection.execute("UPDATE actors SET scopes = '{}' WHERE actor_id = 'stu_001'")
        actor = services.actor("stu_001")

    class ForbiddenClassifier:
        async def classify(self, message):
            raise AssertionError("Invalid authority reached the provider")

    port = security_port(services, FraudAssessor(ForbiddenClassifier()))
    with pytest.raises(ScopeDenied):
        await port.assess_message(FORGED_EMAIL.body, actor)
