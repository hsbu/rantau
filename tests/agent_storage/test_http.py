from fastapi.testclient import TestClient

from backend.agent.router import agent_services
from backend.agent.services import durable_agent_services
from backend.agent.tools import AgentTools
from backend.contracts.enums import Intent
from backend.contracts.models import ScopeDenied
from backend.main import app
from tests.agent.test_graph import FixedClassifier
from tests.agent_storage.conftest import PASSWORD
from tests.fixtures.data import NOW
from tests.fixtures.fakes import FakeReadPort


def test_http_persists_runs_with_real_cookie_sessions_and_only_test_domain_overrides(
    env, monkeypatch
):
    prompts = []

    class Classifier(FixedClassifier):
        async def classify(self, message):
            prompts.append(message)
            return await super().classify(message)

    class StudentReads(FakeReadPort):
        def check(self, actor, operation):
            if (actor.tenant_id, actor.actor_id) != ("demo_001", "stu_001"):
                raise ScopeDenied("Resource unavailable")
            self.calls.append(operation)

    def services():
        # Recreate the graph/services for every request to exercise durable state/run retrieval.
        return durable_agent_services(
            env.database,
            env.auth,
            Classifier(Intent.ASK_POLICY),
            AgentTools(StudentReads(), clock=lambda: NOW),
        )

    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TENANT_ID", "demo_001")
    monkeypatch.setenv("AUTH_TRUSTED_ORIGIN", "http://testserver")
    monkeypatch.setenv("DATABASE_URL", env.database.dsn)
    monkeypatch.setenv("APP_ENV", "test")
    app.dependency_overrides[agent_services] = services
    try:
        with TestClient(app) as client:
            client.cookies.set("session", env.login.token)
            results = [
                client.post(
                    "/api/v1/agent/messages",
                    json=fields,
                )
                for fields in (
                    {"message": "Policy private user@example.org", "conversation_id": "browser"},
                    {"message": "Continue", "conversation_id": "browser"},
                    {"message": "Policy"},
                )
            ]
            assert all(item.status_code == 200 for item in results)
            assert "Prior intent: ASK_POLICY" in prompts[1]
            assert "user@example.org" not in prompts[1]
            assert "Prior intent" not in prompts[2]
            run_id = results[0].json()["run_id"]
            recorded = client.get(f"/api/v1/agent/runs/{run_id}")
            assert recorded.status_code == 200
            assert set(recorded.json()) == set(results[0].json())
            assert "Original chat text is not retained" in recorded.json()["message"]
            assert "user@example.org" not in recorded.text
            assert recorded.json()["tool_events"] == results[0].json()["tool_events"]
            with env.database.connection() as connection:
                assert (
                    connection.execute("SELECT count(*) AS n FROM agent_runs").fetchone()["n"] == 3
                )
                assert (
                    connection.execute("SELECT count(*) AS n FROM agent_conversations").fetchone()[
                        "n"
                    ]
                    == 1
                )
            env.auth.logout(env.login.token)
            assert client.get(f"/api/v1/agent/runs/{run_id}").status_code == 401
    finally:
        app.dependency_overrides.clear()
    # Real sessions alone cannot enable a graph without model configuration.
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("OPENROUTER_MODEL", "")
    with TestClient(app) as client:
        client.cookies.set("session", env.auth.login("student", PASSWORD, "after-logout").token)
        assert client.post("/api/v1/agent/messages", json={"message": "Policy"}).status_code == 503
