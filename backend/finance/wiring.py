"""Build finance services for the application. Missing authority fails closed (503)."""

from dataclasses import dataclass

from fastapi import HTTPException

from backend.authz.policy_models import MandateSnapshot
from backend.authz.policy_repository import PolicyConnection
from backend.authz.policy_transaction import TransactionAuthorization
from backend.authz.service import AuthService
from backend.authz.storage import Database
from backend.contracts.models import (
    ActorContext,
    Approval,
    PaymentIntent,
    PolicyDecision,
    ServiceUnavailable,
)
from backend.dependencies import auth_service, auth_settings
from backend.finance.authority import AuthoritySource, HoldState
from backend.finance.authorization import GateFactory
from backend.finance.executor import ExecutionFinalizer, ExecutionService
from backend.finance.intents import IntentService
from backend.finance.policy_repo import FinancePolicyRepository
from backend.finance.ports import FinancePaymentPort
from backend.finance.provider import SimulatedProvider
from backend.finance.reads import FinanceReads
from backend.finance.records import LockedIntent
from backend.finance.transfers import TransferService
from backend.university.port import ObligationReader, UniversityPortImpl
from backend.university.receipts import UniversityReceipts
from backend.university.reconciliation import CaseService, ReviewService


class UnavailableAuthority:
    """Explicit fail-closed source for integrations whose authority storage is unavailable."""

    def approval(self, connection: PolicyConnection, intent: PaymentIntent) -> Approval | None:
        raise ServiceUnavailable("Approval store is not connected")

    def mandate(
        self, connection: PolicyConnection, intent: PaymentIntent
    ) -> MandateSnapshot | None:
        raise ServiceUnavailable("Mandate store is not connected")

    def hold(self, connection: PolicyConnection, intent: PaymentIntent) -> HoldState:
        raise ServiceUnavailable("Hold store is not connected")


def configured_authority() -> AuthoritySource:
    """Stored B authority bound to the server-configured authentication tenant."""
    from backend.approvals.finance_authority import StoredAuthority

    return StoredAuthority(auth_settings().auth_tenant_id)


@dataclass(frozen=True)
class FinanceServices:
    database: Database
    auth: AuthService
    reads: FinanceReads
    obligations: ObligationReader
    intents: IntentService
    executor: ExecutionService
    transfers: TransferService
    cases: CaseService
    review: ReviewService
    payments: FinancePaymentPort
    university: UniversityPortImpl


def build_services(
    database: Database,
    auth: AuthService,
    authority: AuthoritySource,
) -> FinanceServices:
    from backend.approvals.finalize import finalize_execution
    from backend.approvals.finance_authority import StoredAuthority
    from backend.approvals.wiring import ProtectedAuthorization, build_approval_service

    repository = FinancePolicyRepository(authority)

    def gate(connection: PolicyConnection) -> TransactionAuthorization:
        return TransactionAuthorization(connection, auth, repository)

    execution_gate: GateFactory = gate
    finalize_authorization: ExecutionFinalizer | None = None
    if isinstance(authority, StoredAuthority):
        if authority.tenant_id != auth.tenant_id:
            raise ServiceUnavailable("Authority tenant does not match authentication")
        # Real stored authority may never use a preview-only execution gate.
        approval = build_approval_service(auth)

        def protected(connection: PolicyConnection) -> ProtectedAuthorization:
            return ProtectedAuthorization(connection, approval)

        def finalize(
            connection: PolicyConnection,
            actor: ActorContext,
            locked: LockedIntent,
            decision: PolicyDecision,
        ) -> None:
            finalize_execution(approval, connection, actor, locked, decision)

        execution_gate, finalize_authorization = protected, finalize

    transfers = TransferService(database, SimulatedProvider(database), UniversityReceipts())
    obligations = ObligationReader(database, auth, transfers)
    reads = FinanceReads(database, auth, obligations)
    executor = ExecutionService(
        database, execution_gate, transfers, finalize_authorization=finalize_authorization
    )
    cases = CaseService(database, gate)
    return FinanceServices(
        database=database,
        auth=auth,
        reads=reads,
        obligations=obligations,
        intents=IntentService(database, gate),
        executor=executor,
        transfers=transfers,
        cases=cases,
        review=ReviewService(database),
        payments=FinancePaymentPort(executor, reads),
        university=UniversityPortImpl(obligations, cases),
    )


def finance_services() -> FinanceServices:
    settings = auth_settings()
    if settings.database_url is None:
        raise HTTPException(503, detail={"code": "FINANCE_NOT_CONFIGURED"})
    database = Database(settings.database_url.get_secret_value())
    return build_services(database, auth_service(), configured_authority())
