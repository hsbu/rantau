"""Finance HTTP routes. Identity comes only from the verified session cookie."""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from backend.approvals.service import ApprovalConflict
from backend.contracts.enums import Decision, ReasonCode
from backend.contracts.http import (
    AuditEntry,
    CaseCreated,
    ExecuteRequest,
    ExecutionResult,
    IntentCreated,
)
from backend.contracts.models import (
    ActorContext,
    CaseSubmission,
    FxQuote,
    Identifier,
    IntentProposal,
    PaymentIntentView,
    PaymentOptions,
    PaymentResult,
    ReconciliationCase,
    ScopeDenied,
    ServiceUnavailable,
    TuitionObligationDetail,
    UntrustedDocument,
)
from backend.dependencies import auth_settings, verified_actor
from backend.finance.audit import AuditEvent, AuditWriter
from backend.finance.errors import error_response
from backend.finance.executor import IdempotencyKeyReused
from backend.finance.outcomes import Created, Refused
from backend.finance.reads import audit_entries
from backend.finance.states import InvalidTransition
from backend.finance.wiring import FinanceServices, finance_services

NO_STORE = {"Cache-Control": "no-store"}
# Largest simulated allowance quote request: CNY 1,000,000.00 in fen.
MAX_ALLOWANCE_MINOR = 100_000_000
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
]


class FinanceRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            try:
                result = await handler(request)
            except ScopeDenied:
                return JSONResponse({"detail": "Resource unavailable"}, 404, headers=NO_STORE)
            except ServiceUnavailable:
                return JSONResponse(
                    {"detail": {"code": "FINANCE_UNAVAILABLE"}}, 503, headers=NO_STORE
                )
            except ApprovalConflict as error:
                return JSONResponse({"detail": {"code": error.code}}, 409, headers=NO_STORE)
            result.headers["Cache-Control"] = "no-store"
            return result

        return guarded


def trusted_origin(request: Request) -> None:
    if request.headers.get("origin") != auth_settings().auth_trusted_origin:
        raise HTTPException(403, detail={"code": "UNTRUSTED_ORIGIN"})


router = APIRouter(prefix="/api/v1", tags=["finance"], route_class=FinanceRoute)
Actor = Annotated[ActorContext, Depends(verified_actor)]
Services = Annotated[FinanceServices, Depends(finance_services)]
TrustedOrigin = Depends(trusted_origin)


@router.get("/tuition/obligations", response_model=list[TuitionObligationDetail])
def list_obligations(actor: Actor, services: Services) -> list[TuitionObligationDetail]:
    return list(services.obligations.list(actor))


@router.get("/tuition/obligations/{obligation_id}", response_model=TuitionObligationDetail)
def get_obligation(
    obligation_id: Identifier, actor: Actor, services: Services
) -> TuitionObligationDetail:
    return services.obligations.get(actor, obligation_id)


@router.get("/tuition/obligations/{obligation_id}/payment-options", response_model=PaymentOptions)
def get_payment_options(
    obligation_id: Identifier, actor: Actor, services: Services
) -> PaymentOptions:
    return services.reads.payment_options(actor, obligation_id)


@router.post(
    "/tuition/obligations/{obligation_id}/recheck",
    response_model=TuitionObligationDetail,
    dependencies=[TrustedOrigin],
)
def recheck_obligation(
    obligation_id: Identifier, actor: Actor, services: Services
) -> TuitionObligationDetail:
    return services.obligations.recheck(actor, obligation_id)


@router.get("/quotes", response_model=list[FxQuote])
def list_quotes(
    actor: Actor,
    services: Services,
    obligation_id: Annotated[Identifier | None, Query()] = None,
    destination_amount_minor: Annotated[int | None, Query(ge=1, le=MAX_ALLOWANCE_MINOR)] = None,
    source: Literal["IDR"] = "IDR",
    target: Literal["CNY"] = "CNY",
) -> list[FxQuote]:
    if (obligation_id is None) == (destination_amount_minor is None):
        raise HTTPException(422, detail={"code": "ONE_QUOTE_SUBJECT_REQUIRED"})
    if obligation_id is not None:
        return list(services.reads.quotes(actor, obligation_id))
    assert destination_amount_minor is not None
    return list(services.reads.allowance_quotes(actor, destination_amount_minor))


@router.post(
    "/payment-intents", response_model=IntentCreated, status_code=201, dependencies=[TrustedOrigin]
)
def create_intent(body: IntentProposal, actor: Actor, services: Services) -> Response:
    return _created_response(services.intents.create(actor, body))


@router.get("/payment-intents", response_model=list[PaymentIntentView])
def list_intents(actor: Actor, services: Services) -> list[PaymentIntentView]:
    return list(services.reads.intent_list(actor))


@router.get("/payment-intents/{intent_id}", response_model=PaymentIntentView)
def get_intent(intent_id: Identifier, actor: Actor, services: Services) -> PaymentIntentView:
    return services.reads.intent_view(actor, intent_id)


@router.post(
    "/payment-intents/{intent_id}/execute",
    response_model=ExecutionResult,
    dependencies=[TrustedOrigin],
)
def execute_payment(
    intent_id: Identifier,
    actor: Actor,
    services: Services,
    idempotency_key: IdempotencyKey,
    body: ExecuteRequest | None = None,
) -> Response:
    claimed = body.terms_hash if body else None
    try:
        outcome = services.executor.execute(actor, intent_id, idempotency_key, claimed)
    except IdempotencyKeyReused:
        audit_id = _refusal_audit(
            services, actor, "EXECUTION_REFUSED", intent_id, ReasonCode.IDEMPOTENCY_KEY_REUSED
        )
        return error_response(ReasonCode.IDEMPOTENCY_KEY_REUSED, audit_id, intent_id)
    if isinstance(outcome, Refused):
        owner = services.reads.owner_of_intent(actor.tenant_id, intent_id)
        return error_response(
            outcome.reason_code,
            outcome.audit_event_id,
            intent_id,
            requester_owns_funds=owner == actor.actor_id,
        )
    result = ExecutionResult(
        payment_id=outcome.payment_id,
        transfer_status=outcome.transfer_state,
        audit_event_id=outcome.audit_event_id,
    )
    return JSONResponse(result.model_dump(mode="json"))


@router.post(
    "/payment-intents/{intent_id}/cancel",
    response_model=PaymentIntentView,
    dependencies=[TrustedOrigin],
)
def cancel_intent(intent_id: Identifier, actor: Actor, services: Services) -> Response:
    try:
        services.intents.cancel(actor, intent_id)
    except InvalidTransition:
        audit_id = _refusal_audit(
            services, actor, "CANCEL_REFUSED", intent_id, ReasonCode.PAYMENT_ALREADY_SUBMITTED
        )
        return error_response(ReasonCode.PAYMENT_ALREADY_SUBMITTED, audit_id, intent_id)
    view = services.reads.intent_view(actor, intent_id)
    return JSONResponse(view.model_dump(mode="json"))


@router.post(
    "/payment-intents/{intent_id}/revisions",
    response_model=IntentCreated,
    status_code=201,
    dependencies=[TrustedOrigin],
)
def revise_intent(
    intent_id: Identifier, body: IntentProposal, actor: Actor, services: Services
) -> Response:
    try:
        outcome = services.intents.revise(actor, intent_id, body)
    except InvalidTransition:
        audit_id = _refusal_audit(
            services, actor, "REVISION_REFUSED", intent_id, ReasonCode.PAYMENT_ALREADY_SUBMITTED
        )
        return error_response(ReasonCode.PAYMENT_ALREADY_SUBMITTED, audit_id, intent_id)
    return _created_response(outcome)


@router.get("/documents", response_model=list[UntrustedDocument])
def list_documents(actor: Actor, services: Services) -> list[UntrustedDocument]:
    return list(services.reads.documents(actor))


@router.get("/transfers/{transfer_id}", response_model=PaymentResult)
def get_transfer(transfer_id: Identifier, actor: Actor, services: Services) -> PaymentResult:
    return services.reads.payment_result(actor, transfer_id)


@router.post(
    "/transfers/{transfer_id}/recheck", response_model=PaymentResult, dependencies=[TrustedOrigin]
)
def recheck_transfer(transfer_id: Identifier, actor: Actor, services: Services) -> PaymentResult:
    services.reads.payment_result(actor, transfer_id)
    services.transfers.settle(actor.tenant_id, transfer_id)
    return services.reads.payment_result(actor, transfer_id)


@router.post(
    "/reconciliations", response_model=CaseCreated, status_code=201, dependencies=[TrustedOrigin]
)
def create_case(body: CaseSubmission, actor: Actor, services: Services) -> JSONResponse:
    case = services.cases.create(actor, body)
    created = CaseCreated(
        case_id=case.id, status=case.state.value, evidence_missing=case.evidence_missing
    )
    return JSONResponse(created.model_dump(mode="json"), status_code=201)


@router.get("/reconciliations/{case_id}", response_model=ReconciliationCase)
def get_case(case_id: Identifier, actor: Actor, services: Services) -> ReconciliationCase:
    return services.cases.get(actor, case_id)


@router.post(
    "/reconciliations/{case_id}/submit",
    response_model=ReconciliationCase,
    dependencies=[TrustedOrigin],
)
def submit_case(case_id: Identifier, actor: Actor, services: Services) -> ReconciliationCase:
    return services.cases.submit(actor, case_id)


@router.get("/audit", response_model=list[AuditEntry])
def get_audit(
    actor: Actor, services: Services, resource_id: Annotated[Identifier, Query()]
) -> list[AuditEntry]:
    return list(audit_entries(services.database, services.auth, actor, resource_id))


def _refusal_audit(
    services: FinanceServices,
    actor: ActorContext,
    action: str,
    resource_id: str,
    reason: ReasonCode,
) -> str:
    with services.database.connection() as connection:
        return AuditWriter().record(
            connection,
            AuditEvent(
                tenant_id=actor.tenant_id,
                actor_id=actor.actor_id,
                action=action,
                resource_type="payment_intent",
                resource_id=resource_id,
                reason_code=reason.value,
            ),
        )


def _created_response(outcome: Created | Refused) -> Response:
    if isinstance(outcome, Refused):
        return error_response(outcome.reason_code, outcome.audit_event_id, None)
    decision = outcome.decision
    if decision.decision == Decision.HOLD and decision.reason_code is not None:
        return error_response(decision.reason_code, decision.audit_event_id, outcome.intent.id)
    created = IntentCreated(
        id=outcome.intent.id,
        terms_hash=outcome.intent.terms_hash,
        tier=outcome.intent.tier,
        state=outcome.intent.state,
        approval_required=decision.decision == Decision.REQUIRE_APPROVAL,
        quote_expires_at=outcome.intent.quote_expiry,
    )
    return JSONResponse(created.model_dump(mode="json"), status_code=201)
