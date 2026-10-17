"""Verified cookie sessions; missing trusted configuration still fails closed."""

from fastapi import HTTPException, Request
from pydantic import ValidationError

from backend.authz.service import AuthService, InvalidSession
from backend.authz.storage import Database
from backend.config import Settings
from backend.contracts.models import ActorContext


def auth_settings() -> Settings:
    try:
        settings = Settings()
    except ValidationError:
        raise HTTPException(503, detail={"code": "AUTHENTICATION_NOT_CONFIGURED"}) from None
    if not settings.auth_configured:
        raise HTTPException(503, detail={"code": "AUTHENTICATION_NOT_CONFIGURED"})
    return settings


def auth_service() -> AuthService:
    settings = auth_settings()
    assert settings.database_url is not None
    return AuthService(Database(settings.database_url.get_secret_value()), settings.auth_tenant_id)


def session_token(request: Request) -> str | None:
    cookies = [
        pair.strip().partition("=")[0].strip()
        for header in request.headers.getlist("cookie")
        for pair in header.split(";")
    ]
    if cookies.count("session") != 1:
        return None
    return request.cookies.get("session")


def verified_actor(request: Request) -> ActorContext:
    """Only an opaque cookie verified against current DB records supplies identity."""
    from backend.contracts.models import ServiceUnavailable

    try:
        return auth_service().authenticate(session_token(request))
    except InvalidSession:
        raise HTTPException(401, detail={"code": "AUTHENTICATION_REQUIRED"}) from None
    except ServiceUnavailable:
        raise HTTPException(503, detail={"code": "AUTHENTICATION_UNAVAILABLE"}) from None
