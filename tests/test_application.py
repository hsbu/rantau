from unittest.mock import AsyncMock

import psycopg
from fastapi.testclient import TestClient

from backend.main import app


def test_liveness_does_not_claim_domain_readiness(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setattr("backend.main.database_available", AsyncMock(return_value=False))
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok", "simulation": True}
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["dependencies"]["authentication"] is False


def test_finance_routes_fail_closed_without_trusted_configuration(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    client = TestClient(app)
    paths = app.openapi()["paths"]
    assert "/api/v1/payment-intents/{intent_id}/execute" in paths
    assert "/api/v1/demo/reset" in paths
    for method, path in (
        ("post", "/api/v1/payment-intents/x/execute"),
        ("post", "/api/v1/demo/reset"),
        ("get", "/api/v1/tuition/obligations"),
    ):
        response = getattr(client, method)(path, headers={"Idempotency-Key": "k"})
        assert response.status_code in {401, 503}


def test_the_integrated_wiring_uses_tenant_bound_stored_authority(monkeypatch):
    from types import SimpleNamespace

    from backend.approvals.finance_authority import StoredAuthority
    from backend.finance.wiring import configured_authority

    monkeypatch.setattr(
        "backend.finance.wiring.auth_settings",
        lambda: SimpleNamespace(auth_tenant_id="configured_tenant"),
    )
    authority = configured_authority()
    assert isinstance(authority, StoredAuthority)
    assert authority.tenant_id == "configured_tenant"


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
