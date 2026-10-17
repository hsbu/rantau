"""Scoped obligation reads and the UniversityPort implementation."""

from starlette.concurrency import run_in_threadpool

from backend.authz.access import AccessPolicy
from backend.authz.policy_repository import PolicyConnection
from backend.authz.service import AuthService
from backend.authz.storage import Database
from backend.contracts.auth import SharedField
from backend.contracts.enums import PaymentState, TuitionState
from backend.contracts.models import (
    ActorContext,
    ProviderStatusRef,
    ReconciliationCase,
    ScopeDenied,
    TuitionObligation,
    TuitionObligationDetail,
    UniversityPolicy,
)
from backend.contracts.ports import UniversityPort
from backend.finance.records import Row, fetch
from backend.finance.simclock import sim_now
from backend.finance.transfers import FINAL_STATES, TransferService
from backend.university.ledger import settle_due
from backend.university.obligations import read_obligation
from backend.university.reconciliation import CaseService

TUITION_SUMMARY: frozenset[SharedField] = frozenset({"tuition_summary"})


class ObligationReader:
    def __init__(
        self, database: Database, auth: AuthService, transfers: TransferService | None = None
    ) -> None:
        self.database = database
        self.access = AccessPolicy(auth)
        self.transfers = transfers

    def list(self, actor: ActorContext) -> tuple[TuitionObligationDetail, ...]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM tuition_obligations WHERE tenant_id = %s AND student_id = %s "
                "ORDER BY alias",
                (actor.tenant_id, actor.actor_id),
            ).fetchall()
            self.access.require_student_fields(
                actor, actor.tenant_id, actor.actor_id, TUITION_SUMMARY
            )
            return tuple(self._detail(connection, actor.tenant_id, row) for row in rows)

    def get(self, actor: ActorContext, alias: str) -> TuitionObligationDetail:
        with self.database.connection() as connection:
            row = self._visible(connection, actor, alias)
            return self._detail(connection, actor.tenant_id, row)

    def recheck(self, actor: ActorContext, alias: str) -> TuitionObligationDetail:
        """In-simulation status recheck: poll unsettled transfers, then post what is due."""
        with self.database.connection() as connection:
            row = self._visible(connection, actor, alias)
            pending = [
                transfer["alias"]
                for transfer in connection.execute(
                    "SELECT alias, state FROM transfers WHERE tenant_id = %s "
                    "AND obligation_alias = %s",
                    (actor.tenant_id, row["alias"]),
                ).fetchall()
                if PaymentState(transfer["state"]) not in FINAL_STATES
            ]
        for transfer_alias in pending:
            if self.transfers is not None:
                self.transfers.settle(actor.tenant_id, transfer_alias)
        with self.database.connection() as connection:
            settle_due(connection, actor.tenant_id, alias)
        return self.get(actor, alias)

    def _visible(self, connection: PolicyConnection, actor: ActorContext, alias: str) -> Row:
        row = fetch(connection, "obligation", actor.tenant_id, alias)
        if row is None:
            raise ScopeDenied("Resource unavailable")
        self.access.require_student_fields(
            actor, actor.tenant_id, row["student_id"], TUITION_SUMMARY
        )
        return row

    def _detail(
        self, connection: PolicyConnection, tenant_id: str, row: Row
    ) -> TuitionObligationDetail:
        snapshot = read_obligation(connection, tenant_id, row, sim_now(connection, tenant_id))
        obligation = snapshot.obligation
        shortfall = (
            obligation.balance_minor if obligation.state == TuitionState.PARTIALLY_POSTED else 0
        )
        policy = connection.execute(
            "SELECT policy FROM university_policies WHERE tenant_id = %s AND alias = %s",
            (tenant_id, row["policy_alias"]),
        ).fetchone()
        topup = bool(
            shortfall and policy and UniversityPolicy.model_validate(policy["policy"]).topup_allowed
        )
        provider = (
            ProviderStatusRef(
                payment_id=snapshot.latest_transfer_id,
                transfer_status=snapshot.latest_transfer_state,
            )
            if snapshot.latest_transfer_id and snapshot.latest_transfer_state
            else None
        )
        return TuitionObligationDetail(
            **obligation.model_dump(),
            provider_status=provider,
            posting_deadline_at=snapshot.posting_deadline_at,
            active_case_id=snapshot.active_case_id,
            shortfall_minor=shortfall,
            topup_permitted=topup,
        )


class UniversityPortImpl(UniversityPort):
    def __init__(self, obligations: ObligationReader, cases: CaseService) -> None:
        self.obligations = obligations
        self.cases = cases

    async def obligation(self, obligation_id: str, actor: ActorContext) -> TuitionObligation:
        return await run_in_threadpool(self.obligations.get, actor, obligation_id)

    async def reconcile(self, case_id: str, actor: ActorContext) -> ReconciliationCase:
        """Submit or recheck a case; approval and posting stay with the review service."""
        return await run_in_threadpool(self.cases.submit, actor, case_id)
