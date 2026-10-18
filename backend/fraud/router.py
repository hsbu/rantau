"""Authenticated, scoped case reads; no public hold or reviewer mutation routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.authz.router import AuthRoute
from backend.authz.service import AuthService
from backend.contracts.models import ActorContext, Identifier, ServiceUnavailable
from backend.contracts.security import SecurityCaseList, SecurityCaseView
from backend.dependencies import auth_service, verified_actor
from backend.fraud.finance_access import build_security_service
from backend.fraud.security_cases import SecurityCase

router = APIRouter(prefix="/api/v1", tags=["security"], route_class=AuthRoute)
Actor = Annotated[ActorContext, Depends(verified_actor)]
Auth = Annotated[AuthService, Depends(auth_service)]


def _view(case: SecurityCase) -> SecurityCaseView:
    """Project storage into the approved public fields only."""
    return SecurityCaseView.model_validate(
        {
            "case_id": case.case_id,
            "resource_id": case.resource_id,
            "state": case.state.value,
            "reason": case.reason.value,
            "created_at": case.created_at,
            "updated_at": case.updated_at,
            "audit_event_id": case.audit_event_id,
        }
    )


@router.get("/security-cases", response_model=SecurityCaseList)
def list_security_cases(actor: Actor, auth: Auth) -> SecurityCaseList:
    try:
        with auth.database.connection() as connection, connection.transaction():
            # Same revalidation as the single-case read: storage scope alone does
            # not revalidate a session or scopes captured before this transaction.
            auth.current_actor(connection, actor)
            cases = build_security_service(auth).list_cases(connection, actor)
            return SecurityCaseList(cases=tuple(_view(case) for case in cases))
    except ServiceUnavailable:
        raise HTTPException(503, detail={"code": "SECURITY_CASE_UNAVAILABLE"}) from None


@router.get("/security-cases/{id}", response_model=SecurityCaseView)
def get_security_case(id: Identifier, actor: Actor, auth: Auth) -> SecurityCaseView:
    try:
        with auth.database.connection() as connection, connection.transaction():
            # Recheck even the reporter: storage's own-case shortcut does not
            # revalidate a session or scopes captured before this transaction.
            auth.current_actor(connection, actor)
            case = build_security_service(auth).get_case(connection, actor, id)
            return _view(case)
    except ServiceUnavailable:
        raise HTTPException(503, detail={"code": "SECURITY_CASE_UNAVAILABLE"}) from None
