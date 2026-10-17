"""Credential/session and sharing routes; no financial action is exposed here."""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from backend.authz.service import AuthService, InvalidSession, LoginThrottled
from backend.contracts.auth import ConsentRequest, ConsentSummary, LoginRequest, SessionSummary
from backend.contracts.models import ActorContext, Identifier, ScopeDenied, ServiceUnavailable
from backend.dependencies import auth_service, auth_settings, session_token, verified_actor


class AuthRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            try:
                if request.method in {"POST", "PUT", "DELETE"}:
                    settings = auth_settings()
                    if (
                        request.headers.get("origin") != settings.auth_trusted_origin
                        or request.headers.get("sec-fetch-site") == "cross-site"
                    ):
                        raise HTTPException(403, detail={"code": "UNTRUSTED_ORIGIN"})
                    body = bytearray()
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > 4096:
                            return JSONResponse(
                                {"detail": {"code": "AUTH_REQUEST_TOO_LARGE"}},
                                413,
                                headers={"Cache-Control": "no-store"},
                            )
                        body.extend(chunk)
                    if (
                        request.method == "DELETE" or request.url.path == "/api/v1/auth/logout"
                    ) and body.strip():
                        raise HTTPException(422, detail={"code": "INVALID_AUTH_REQUEST"})
                    # Restore the bounded body for FastAPI's standard typed parsing.
                    request._body = bytes(body)
                result = await handler(request)
                result.headers["Cache-Control"] = "no-store"
                return result
            except RequestValidationError:
                return JSONResponse(
                    {"detail": {"code": "INVALID_AUTH_REQUEST"}},
                    422,
                    headers={"Cache-Control": "no-store"},
                )
            except InvalidSession:
                return JSONResponse(
                    {"detail": {"code": "AUTHENTICATION_REQUIRED"}},
                    401,
                    headers={"Cache-Control": "no-store"},
                )
            except LoginThrottled:
                return JSONResponse(
                    {"detail": {"code": "LOGIN_THROTTLED"}},
                    429,
                    headers={"Retry-After": "900", "Cache-Control": "no-store"},
                )
            except ScopeDenied:
                return JSONResponse(
                    {"detail": "Resource unavailable"}, 404, headers={"Cache-Control": "no-store"}
                )
            except ServiceUnavailable:
                return JSONResponse(
                    {"detail": {"code": "AUTHENTICATION_UNAVAILABLE"}},
                    503,
                    headers={"Cache-Control": "no-store"},
                )
            except HTTPException as error:
                return JSONResponse(
                    {"detail": error.detail},
                    error.status_code,
                    headers={"Cache-Control": "no-store", **(error.headers or {})},
                )

        return guarded


router = APIRouter(prefix="/api/v1", tags=["authentication"], route_class=AuthRoute)
Service = Annotated[AuthService, Depends(auth_service)]
Actor = Annotated[ActorContext, Depends(verified_actor)]


@router.post("/auth/login", response_model=SessionSummary)
def login(
    body: LoginRequest, request: Request, response: Response, service: Service
) -> SessionSummary:
    peer = request.client.host if request.client else "unknown-client"
    session = service.login(body.username, body.password.get_secret_value(), peer)
    response.set_cookie(
        "session",
        session.token,
        max_age=3600,
        httponly=True,
        samesite="strict",
        path="/",
        secure=auth_settings().auth_cookie_secure,
    )
    return SessionSummary(role=session.actor.role)


@router.get("/auth/session", response_model=SessionSummary)
def session(actor: Actor) -> SessionSummary:
    return SessionSummary(role=actor.role)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, actor: Actor, service: Service) -> Response:
    token = session_token(request)
    assert token is not None
    service.logout(token)
    response = Response(status_code=204)
    response.delete_cookie(
        "session",
        path="/",
        httponly=True,
        samesite="strict",
        secure=auth_settings().auth_cookie_secure,
    )
    return response


@router.put("/student/sharing-consents/{sponsor_id}", response_model=ConsentSummary)
def grant_consent(
    sponsor_id: Identifier, body: ConsentRequest, actor: Actor, service: Service
) -> ConsentSummary:
    try:
        return service.grant_consent(actor, sponsor_id, body.allowed_shared_fields, body.expires_at)
    except ValueError:
        raise HTTPException(422, detail={"code": "INVALID_SHARING_REQUEST"}) from None


@router.delete("/student/sharing-consents/{sponsor_id}", status_code=204)
def revoke_consent(sponsor_id: Identifier, actor: Actor, service: Service) -> Response:
    service.revoke_consent(actor, sponsor_id)
    return Response(status_code=204)
