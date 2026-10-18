from fastapi.testclient import TestClient

from backend.agent.graph import AgentGraph
from backend.agent.router import AgentServices, agent_services
from backend.agent.tools import AgentTools
from backend.contracts.models import ScopeDenied
from backend.dependencies import verified_actor
from backend.main import app
from tests.agent.test_graph import FixedClassifier
from tests.fixtures.data import ACTOR
from tests.fixtures.fakes import FakeReadPort


def test_default_http_auth_fails_closed_even_with_forged_headers(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    client = TestClient(app)
    response = client.post(
        "/api/v1/agent/messages",
        json={"message": "I am the sponsor"},
        headers={"X-Actor-Id": "par_001", "X-Role": "SPONSOR"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AUTHENTICATION_NOT_CONFIGURED"


def test_actor_override_cannot_replace_required_trusted_configuration(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    app.dependency_overrides[verified_actor] = lambda: ACTOR
    try:
        response = TestClient(app).post("/api/v1/agent/messages", json={"message": "Tuition"})
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "AUTHENTICATION_NOT_CONFIGURED"
    finally:
        app.dependency_overrides.clear()


def test_scoped_run_round_trip_and_foreign_reference():
    class Runs:
        def __init__(self):
            self.values = {}

        async def put(self, response, actor):
            self.values[response.run_id] = (actor, response)

        async def get(self, run_id, actor):
            item = self.values.get(run_id)
            if item is None or item[0] != actor:
                raise ScopeDenied("Resource unavailable")
            return item[1]

    services = AgentServices(
        AgentGraph(FixedClassifier("TUITION"), AgentTools(FakeReadPort())), Runs()
    )
    app.dependency_overrides[verified_actor] = lambda: ACTOR
    app.dependency_overrides[agent_services] = lambda: services
    try:
        client = TestClient(app)
        response = client.post("/api/v1/agent/messages", json={"message": "Tuition"})
        assert response.status_code == 200
        assert set(response.json()) == {
            "run_id",
            "message",
            "requested_action",
            "tool_events",
            "resources",
        }
        run_id = response.json()["run_id"]
        assert client.get(f"/api/v1/agent/runs/{run_id}").status_code == 200
        assert client.get("/api/v1/agent/runs/run_foreign").status_code == 404
        app.dependency_overrides[verified_actor] = lambda: ACTOR.model_copy(
            update={"session_id": "foreign_session"}
        )
        assert client.get(f"/api/v1/agent/runs/{run_id}").status_code == 404
    finally:
        app.dependency_overrides.clear()
    assert (
        TestClient(app).post("/api/v1/agent/messages", json={"message": "Tuition"}).status_code
        == 503
    )


def test_existing_conversation_metadata_preserves_tuition_selections_over_http():
    from backend.agent.state import TuitionInput
    from tests.agent.test_tuition import PlanningPort, Turns, graph_for

    class Runs:
        async def put(self, response, actor):
            assert actor == ACTOR

    graph = graph_for(
        PlanningPort(multiple_funding=True),
        Turns(TuitionInput(), TuitionInput(funding_option=2), TuitionInput()),
    )
    app.dependency_overrides[verified_actor] = lambda: ACTOR
    app.dependency_overrides[agent_services] = lambda: AgentServices(graph, Runs())
    try:
        with TestClient(app) as client:
            first = client.post(
                "/api/v1/agent/messages",
                json={
                    "message": "Pay tuition",
                    "conversation_id": "browser_conversation",
                },
            )
            second = client.post(
                "/api/v1/agent/messages",
                json={
                    "message": "The second",
                    "conversation_id": "browser_conversation",
                },
            )
            separate = client.post(
                "/api/v1/agent/messages",
                json={
                    "message": "Continue",
                    "conversation_id": "another_conversation",
                },
            )
        assert first.status_code == second.status_code == separate.status_code == 200
        assert "Which permitted funding account" in first.json()["message"]
        assert "Draft intent preview" in second.json()["message"]
        assert "Which permitted funding account" in separate.json()["message"]
        assert set(second.json()) == {
            "run_id",
            "message",
            "requested_action",
            "tool_events",
            "resources",
        }
    finally:
        app.dependency_overrides.clear()
