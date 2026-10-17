"""Protected owner authority routes; no execution/consumption endpoint exists."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from backend.approvals.service import ApprovalConflict, ApprovalService
from backend.authz.router import AuthRoute
from backend.contracts.authority import ApprovalView, MandateRequest, MandateView
from backend.contracts.enums import Role
from backend.contracts.http import SponsorDecisionRequest, SponsorDecisionResult
from backend.contracts.models import (
    ActorContext,
    ApprovalRequest,
    Identifier,
    ScopeDenied,
    ServiceUnavailable,
)
from backend.dependencies import auth_service, auth_settings, verified_actor


def approval_service() -> ApprovalService:
    # Dev C must explicitly install its trusted adapter. No fallback financial
    # store or fake gate is available in the running application.
    return ApprovalService(auth_service(), None, auth_settings().approval_ttl_seconds)


def _call[T](operation: Callable[[], T]) -> T:
    try:
        return operation()
    except ApprovalConflict as error:
        raise HTTPException(409, detail={"code": error.code}) from None
    except ServiceUnavailable:
        raise HTTPException(503, detail={"code": "AUTHORITY_UNAVAILABLE"}) from None


def _role(actor: ActorContext, expected: Role) -> None:
    if actor.role != expected:
        raise ScopeDenied()


async def empty_body(request: Request) -> None:
    if (await request.body()).strip():
        raise HTTPException(422, detail={"code": "INVALID_AUTHORITY_REQUEST"})


router = APIRouter(prefix="/api/v1", tags=["authority"], route_class=AuthRoute)
Service = Annotated[ApprovalService, Depends(approval_service)]
Actor = Annotated[ActorContext, Depends(verified_actor)]


@router.post(
    "/payment-intents/{id}/approval-requests",
    response_model=ApprovalRequest,
    dependencies=[Depends(empty_body)],
)
def request_approval(id: Identifier, actor: Actor, service: Service) -> ApprovalRequest:
    return _call(lambda: service.request(actor, id))


@router.get("/sponsor/approvals", response_model=list[ApprovalView])
def sponsor_approvals(actor: Actor, service: Service) -> list[ApprovalView]:
    _role(actor, Role.SPONSOR)
    return _call(lambda: service.list_approvals(actor))


@router.post("/sponsor/approvals/{id}/decision", response_model=SponsorDecisionResult)
def sponsor_decision(
    id: Identifier, body: SponsorDecisionRequest, actor: Actor, service: Service
) -> SponsorDecisionResult:
    _role(actor, Role.SPONSOR)
    return _call(lambda: service.decide(actor, id, body.decision, body.terms_hash))


@router.get("/student/approvals", response_model=list[ApprovalView])
def student_approvals(actor: Actor, service: Service) -> list[ApprovalView]:
    _role(actor, Role.STUDENT)
    return _call(lambda: service.list_approvals(actor))


@router.post("/student/approvals/{id}/decision", response_model=SponsorDecisionResult)
def student_decision(
    id: Identifier, body: SponsorDecisionRequest, actor: Actor, service: Service
) -> SponsorDecisionResult:
    _role(actor, Role.STUDENT)
    return _call(lambda: service.decide(actor, id, body.decision, body.terms_hash))


@router.get("/sponsor/mandates", response_model=list[MandateView])
def sponsor_mandates(actor: Actor, service: Service) -> list[MandateView]:
    _role(actor, Role.SPONSOR)
    return _call(lambda: service.list_mandates(actor))


@router.post("/sponsor/mandates", response_model=MandateView)
def create_mandate(body: MandateRequest, actor: Actor, service: Service) -> MandateView:
    return _call(lambda: service.save_mandate(actor, body))


@router.put("/sponsor/mandates/{id}", response_model=MandateView)
def update_mandate(
    id: Identifier, body: MandateRequest, actor: Actor, service: Service
) -> MandateView:
    return _call(lambda: service.save_mandate(actor, body, id))


@router.delete("/sponsor/mandates/{id}", status_code=204)
def revoke_mandate(id: Identifier, actor: Actor, service: Service) -> Response:
    _call(lambda: service.revoke_mandate(actor, id))
    return Response(status_code=204)
