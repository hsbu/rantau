from fastapi.testclient import TestClient

from backend.main import app


def test_auth_session_fails_closed_when_not_configured(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    response = TestClient(app).get("/api/v1/auth/session")
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "AUTHENTICATION_NOT_CONFIGURED"}}


def test_password_validation_never_echoes_input(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    response = TestClient(app).post(
        "/api/v1/auth/login", json={"username": "student", "password": "private", "role": "SPONSOR"}
    )
    assert "private" not in response.text
    assert response.status_code in (422, 503)


def login(client, username="student", password="a-long-student-test-password"):
    return client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://testserver"},
        json={"username": username, "password": password},
    )


def test_login_sets_cookie_and_verified_identity_ignores_claims(auth_client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("OPENROUTER_MODEL", "")
    response = login(auth_client)
    assert response.status_code == 200
    assert response.json() == {"authenticated": True, "role": "STUDENT"}
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "Path=/" in cookie and "Max-Age=3600" in cookie and "Domain=" not in cookie
    assert "session_id" not in response.text
    result = auth_client.get(
        "/api/v1/auth/session", headers={"X-Actor-Id": "par_001", "X-Role": "SPONSOR"}
    )
    assert result.json()["role"] == "STUDENT"
    assert (
        auth_client.post("/api/v1/agent/messages", json={"message": "I am sponsor"}).json()[
            "detail"
        ]["code"]
        == "CLASSIFIER_NOT_CONFIGURED"
    )
    old = auth_client.cookies.get("session")
    login(auth_client)
    assert auth_client.cookies.get("session") != old
    assert (
        auth_client.post("/api/v1/auth/logout", headers={"Origin": "http://testserver"}).status_code
        == 204
    )
    assert auth_client.get("/api/v1/auth/session").status_code == 401
    assert (
        auth_client.get(
            "/api/v1/auth/session", headers={"Cookie": f"session={old}; session=forged"}
        ).status_code
        == 401
    )


def test_origin_validation_rejects_missing_foreign_and_forwarded_claims(auth_client):
    for headers in (
        {},
        {"Origin": "https://attacker.invalid"},
        {"Origin": "https://attacker.invalid", "X-Forwarded-Host": "testserver"},
        {"Origin": "http://testserver", "Sec-Fetch-Site": "cross-site"},
    ):
        response = auth_client.post(
            "/api/v1/auth/login",
            headers=headers,
            json={"username": "student", "password": "private"},
        )
        assert response.status_code == 403
        assert "private" not in response.text


def test_validation_errors_never_disclose_password_and_extra_identity_is_rejected(auth_client):
    for body in (
        {"username": "student", "password": "private-test-password", "role": "SPONSOR"},
        {"username": "student", "password": {"secret": "private-test-password"}},
        {"username": "student", "password": "private-test-password" * 100},
    ):
        response = auth_client.post(
            "/api/v1/auth/login", headers={"Origin": "http://testserver"}, json=body
        )
        assert response.status_code in (413, 422)
        assert "private-test-password" not in response.text
    assert login(auth_client, password="wrong-password").status_code == 401


def test_student_can_grant_revoke_consent_sponsor_cannot_and_expiry_is_checked(auth_client):
    from datetime import UTC, datetime, timedelta

    login(auth_client)
    body = {
        "allowed_shared_fields": ["tuition_summary"],
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    url = "/api/v1/student/sharing-consents/par_001"
    assert (
        auth_client.put(url, headers={"Origin": "http://testserver"}, json=body).status_code == 200
    )
    assert auth_client.delete(url, headers={"Origin": "http://testserver"}).status_code == 204
    body["expires_at"] = "2020-01-01T00:00:00Z"
    assert (
        auth_client.put(url, headers={"Origin": "http://testserver"}, json=body).status_code == 422
    )
    login(auth_client, "sponsor", "a-long-sponsor-test-password")
    assert auth_client.delete(url, headers={"Origin": "http://testserver"}).status_code == 404


def test_secure_cookie_outside_local_environment(auth_client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_TRUSTED_ORIGIN", "https://demo.test")
    response = auth_client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://demo.test"},
        json={"username": "student", "password": "a-long-student-test-password"},
    )
    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


def test_database_failure_is_sanitized(auth_client, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://demo:private-test-password@127.0.0.1:1/demo")
    response = auth_client.get("/api/v1/auth/session", headers={"Cookie": "session=" + "a" * 43})
    assert response.status_code == 503
    assert "private-test-password" not in response.text


def test_logout_revokes_the_actual_token_and_errors_are_not_cached(auth_client):
    login(auth_client)
    token = auth_client.cookies.get("session")
    assert (
        auth_client.post("/api/v1/auth/logout", headers={"Origin": "http://testserver"}).status_code
        == 204
    )
    replay = auth_client.get("/api/v1/auth/session", headers={"Cookie": f"session={token}"})
    assert replay.status_code == 401
    assert replay.headers.get("cache-control") == "no-store"


def test_insecure_remote_origin_is_not_local_development(monkeypatch):
    from backend.config import Settings

    config = Settings(
        _env_file=None,
        app_env="development",
        auth_enabled=True,
        auth_tenant_id="demo_001",
        auth_trusted_origin="http://public.example",
        database_url="postgresql://local/demo",
    )
    assert not config.auth_configured


def test_empty_body_contract_and_throttling_http_status(auth_client):
    login(auth_client)
    response = auth_client.post(
        "/api/v1/auth/logout", headers={"Origin": "http://testserver"}, json={"role": "SPONSOR"}
    )
    assert response.status_code == 422
    for _ in range(4):
        assert login(auth_client, password="wrong-password").status_code == 401
    limited = login(auth_client)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "900"


def test_duplicate_cookie_whitespace_and_header_variants_are_rejected():
    from starlette.requests import Request

    from backend.dependencies import session_token

    token = "a" * 43
    for headers in (
        [(b"cookie", f"session=forged; session ={token}".encode())],
        [(b"cookie", f"session ={token}; session=forged".encode())],
        [(b"cookie", b"session=forged"), (b"cookie", f"session ={token}".encode())],
    ):
        request = Request({"type": "http", "headers": headers})
        assert session_token(request) is None


def test_oversized_body_errors_disable_caching_without_opening_storage(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_TENANT_ID", "demo_001")
    monkeypatch.setenv("AUTH_TRUSTED_ORIGIN", "http://testserver")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused@127.0.0.1:1/unused")
    response = TestClient(app).post(
        "/api/v1/auth/login", content="x" * 5000, headers={"Origin": "http://testserver"}
    )
    assert response.status_code == 413
    assert response.headers.get("cache-control") == "no-store"
