"""Build finance services for the application. Missing authority fails closed (503)."""

from dataclasses import dataclass

from fastapi import HTTPException

from backend.authz.policy_models import MandateSnapshot
from backend.authz.policy_repository import PolicyConnection
from backend.authz.policy_transaction import TransactionAuthorization
from backend.authz.service import AuthService
from backend.authz.storage import Database
from backend.contracts.models import Approval, PaymentIntent, ServiceUnavailable
from backend.dependencies import auth_service, auth_settings
from backend.finance.authority import AuthoritySource, HoldState
from backend.finance.executor import ExecutionService
from backend.finance.intents import IntentService
from backend.finance.policy_repo import FinancePolicyRepository
from backend.finance.ports import FinancePaymentPort
from backend.finance.provider import SimulatedProvider
from backend.finance.reads import FinanceReads
from backend.finance.transfers import TransferService
from backend.university.port import ObligationReader, UniversityPortImpl
from backend.university.receipts import UniversityReceipts
from backend.university.reconciliation import CaseService, ReviewService


class UnavailableAuthority:
    """Stands in until Dev B's approval, mandate and hold stores exist; every use fails closed."""

    def approval(self, connection: PolicyConnection, intent: PaymentIntent) -> Approval | None:
        raise ServiceUnavailable("Approval store is not connected")

    def mandate(
        self, connection: PolicyConnection, intent: PaymentIntent
    ) -> MandateSnapshot | None:
        raise ServiceUnavailable("Mandate store is not connected")

    def hold(self, connection: PolicyConnection, intent: PaymentIntent) -> HoldState:
        raise ServiceUnavailable("Hold store is not connected")


def configured_authority() -> AuthoritySource:
    """Replace with Dev B's stores when they exist; never a scripted or permissive source."""
    return UnavailableAuthority()


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
    database: Database, auth: AuthService, authority: AuthoritySource
) -> FinanceServices:
    repository = FinancePolicyRepository(authority)

    def gate(connection: PolicyConnection) -> TransactionAuthorization:
        return TransactionAuthorization(connection, auth, repository)

    transfers = TransferService(database, SimulatedProvider(database), UniversityReceipts())
    obligations = ObligationReader(database, auth, transfers)
    reads = FinanceReads(database, auth, obligations)
    executor = ExecutionService(database, gate, transfers)
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
