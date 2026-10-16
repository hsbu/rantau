from unittest.mock import AsyncMock

import psycopg
from fastapi.testclient import TestClient

from backend.main import app


def test_liveness_does_not_claim_domain_readiness(monkeypatch):
    monkeypatch.setattr("backend.main.database_available", AsyncMock(return_value=False))
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok", "simulation": True}
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["dependencies"]["authentication"] is False


def test_no_finance_executor_or_fake_gate_is_exposed():
    paths = app.openapi()["paths"]
    assert "/api/v1/payment-intents/{id}/execute" not in paths
    assert "/api/v1/demo/reset" not in paths


def test_failed_database_connection_is_sanitized(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://demo:synthetic-private-password@127.0.0.1/demo"
    )
    monkeypatch.setattr(
        "backend.main.psycopg.AsyncConnection.connect",
        AsyncMock(side_effect=psycopg.OperationalError("synthetic-private-password")),
    )
    response = TestClient(app).get("/ready")
    assert response.status_code == 503
    assert response.json()["dependencies"]["database"] is False
    assert "synthetic-private-password" not in response.text
