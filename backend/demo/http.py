"""Demo controls. Admin-only, development/test only, and closed unless an admin is provisioned."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.config import Settings
from backend.contracts.enums import Role
from backend.contracts.http import (
    AdvanceClockRequest,
    AuditEntry,
    DemoState,
    DocumentInjectRequest,
    FaultRequest,
    ResetRequest,
    ResetResult,
    ScenarioInfo,
    TickResult,
)
from backend.contracts.models import ActorContext, ScopeDenied
from backend.demo.reset import DEMO_ENVIRONMENTS, reset_demo_fixture
from backend.demo.scenarios import SCENARIOS, STUDENT_ID, scenario
from backend.dependencies import verified_actor
from backend.finance.executor import IDEMPOTENCY_RETENTION, prune_idempotency_keys
from backend.finance.http import FinanceRoute, TrustedOrigin
from backend.finance.provider import set_fault
from backend.finance.simclock import advance_sim_clock
from backend.finance.wiring import FinanceServices, finance_services
from backend.university.ledger import settle_due

ADMIN_SCOPE = "demo:manage"
AUDIT_PAGE = 100


def demo_admin(actor: Annotated[ActorContext, Depends(verified_actor)]) -> ActorContext:
    if (
        actor.role != Role.DEMO_ADMIN
        or ADMIN_SCOPE not in actor.scopes
        or Settings().app_env not in DEMO_ENVIRONMENTS
    ):
        raise ScopeDenied("Resource unavailable")
    return actor


router = APIRouter(
    prefix="/api/v1/demo",
    tags=["demo"],
    route_class=FinanceRoute,
    dependencies=[Depends(demo_admin)],
)
Admin = Annotated[ActorContext, Depends(demo_admin)]
Services = Annotated[FinanceServices, Depends(finance_services)]


@router.get("/scenarios", response_model=list[ScenarioInfo])
def list_scenarios() -> list[ScenarioInfo]:
    return [ScenarioInfo(id=spec.id, description=spec.description) for spec in SCENARIOS.values()]


@router.get("/state", response_model=DemoState)
def current_state(admin: Admin, services: Services) -> DemoState:
    with services.database.connection() as connection:
        row = connection.execute(
            "SELECT scenario_id,run_no FROM demo_state WHERE tenant_id=%s", (admin.tenant_id,)
        ).fetchone()
    return DemoState(
        scenario_id=row["scenario_id"] if row else None, run_no=int(row["run_no"]) if row else 0
    )


@router.post("/reset", response_model=ResetResult, dependencies=[TrustedOrigin])
def reset(body: ResetRequest, admin: Admin, services: Services) -> ResetResult:
    try:
        scenario(body.scenario_id)
    except ValueError:
        raise HTTPException(422, detail={"code": "UNKNOWN_SCENARIO"}) from None
    run_no = reset_demo_fixture(services.database, admin.tenant_id, body.scenario_id)
    return ResetResult(scenario_id=body.scenario_id, run_no=run_no)


@router.post("/clock/advance", status_code=204, dependencies=[TrustedOrigin])
def advance_clock(body: AdvanceClockRequest, admin: Admin, services: Services) -> None:
    with services.database.connection() as connection:
        try:
            advance_sim_clock(connection, admin.tenant_id, body.hours * 3600)
        except ValueError:
            raise HTTPException(409, detail={"code": "NO_DEMO_RUN"}) from None


@router.post("/faults", status_code=204, dependencies=[TrustedOrigin])
def inject_fault(body: FaultRequest, admin: Admin, services: Services) -> None:
    with services.database.connection() as connection:
        set_fault(connection, admin.tenant_id, body.provider, body.mode, body.remaining)


@router.post("/university/tick", response_model=TickResult, dependencies=[TrustedOrigin])
def university_tick(admin: Admin, services: Services) -> TickResult:
    """The simulated university posts due receipts and reviews submitted cases."""
    with services.database.connection() as connection:
        posted = settle_due(connection, admin.tenant_id)
        prune_idempotency_keys(connection, admin.tenant_id, IDEMPOTENCY_RETENTION)
    reviewed = services.review.review_submitted(admin.tenant_id)
    return TickResult(postings_made=posted, cases_reviewed=tuple(reviewed))


@router.post("/documents", status_code=204, dependencies=[TrustedOrigin])
def inject_document(body: DocumentInjectRequest, admin: Admin, services: Services) -> None:
    """Plant third-party content the agent may read as data; it is never an instruction."""
    with services.database.connection() as connection:
        connection.execute(
            "INSERT INTO untrusted_documents (tenant_id, alias, student_id, kind, title, body, "
            "claimed_sender) VALUES (%s, 'doc_' || substr(md5(random()::text), 1, 12), %s, %s, "
            "%s, %s, %s)",
            (admin.tenant_id, STUDENT_ID, body.kind, body.title, body.body, body.claimed_sender),
        )


@router.get("/audit", response_model=list[AuditEntry])
def audit_trail(admin: Admin, services: Services) -> list[AuditEntry]:
    with services.database.connection() as connection:
        rows = connection.execute(
            "SELECT audit_event_id, run_no, action, resource_id, decision, reason_code, created_at "
            "FROM audit_events WHERE tenant_id = %s AND run_no = "
            "COALESCE((SELECT run_no FROM demo_state WHERE tenant_id = %s), 0) "
            "ORDER BY created_at DESC LIMIT %s",
            (admin.tenant_id, admin.tenant_id, AUDIT_PAGE),
        ).fetchall()
    return [AuditEntry(**row) for row in rows]
