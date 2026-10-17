"""Port implementations consumed by the agent and other services (all scope-checked)."""

from starlette.concurrency import run_in_threadpool

from backend.contracts.models import (
    ActorContext,
    ApprovalRequest,
    CaseSubmission,
    FraudAssessment,
    FxQuote,
    IntentProposal,
    PaymentIntent,
    PaymentResult,
    PermissionSummary,
    ReconciliationCase,
    ServiceUnavailable,
    ToolResponse,
    TrustedBeneficiary,
    TuitionObligation,
    UniversityPolicy,
)
from backend.contracts.ports import AgentReadPort, PaymentPort, ProposalPort
from backend.finance.errors import build_error
from backend.finance.executor import ExecutionService
from backend.finance.intents import IntentService
from backend.finance.outcomes import Created, Refused
from backend.finance.reads import FinanceReads
from backend.university.port import ObligationReader
from backend.university.reconciliation import CaseService


class PaymentRefused(Exception):
    """The protected executor refused; the typed refusal carries the reason and audit ID."""

    def __init__(self, refused: Refused) -> None:
        super().__init__(refused.reason_code.value)
        self.refused = refused


class FinancePaymentPort(PaymentPort):
    def __init__(self, executor: ExecutionService, reads: FinanceReads) -> None:
        self.executor = executor
        self.reads = reads

    async def execute(
        self, intent_id: str, idempotency_key: str, actor: ActorContext
    ) -> PaymentResult:
        outcome = await run_in_threadpool(self.executor.execute, actor, intent_id, idempotency_key)
        if isinstance(outcome, Refused):
            raise PaymentRefused(outcome)
        return await run_in_threadpool(self.reads.payment_result, actor, outcome.payment_id)

    async def status(self, payment_id: str, actor: ActorContext) -> PaymentResult:
        return await run_in_threadpool(self.reads.payment_result, actor, payment_id)


class FinanceAgentReadPort(AgentReadPort):
    """Read-only; fraud assessment belongs to Dev B and is deliberately not faked here."""

    def __init__(self, reads: FinanceReads, obligations: ObligationReader) -> None:
        self.reads = reads
        self.obligation_reader = obligations

    async def obligations(self, actor: ActorContext) -> tuple[TuitionObligation, ...]:
        return await run_in_threadpool(self.obligation_reader.list, actor)

    async def policy(self, actor: ActorContext) -> UniversityPolicy:
        return await run_in_threadpool(self.reads.policy, actor)

    async def permissions(self, actor: ActorContext) -> tuple[PermissionSummary, ...]:
        return await run_in_threadpool(self.reads.permissions, actor)

    async def beneficiary(self, beneficiary_id: str, actor: ActorContext) -> TrustedBeneficiary:
        return await run_in_threadpool(self.reads.beneficiary, actor, beneficiary_id)

    async def quotes(self, obligation_id: str, actor: ActorContext) -> tuple[FxQuote, ...]:
        return await run_in_threadpool(self.reads.quotes, actor, obligation_id)

    async def payment_status(self, payment_id: str, actor: ActorContext) -> PaymentResult:
        return await run_in_threadpool(self.reads.payment_result, actor, payment_id)

    async def obligation(self, obligation_id: str, actor: ActorContext) -> TuitionObligation:
        return await run_in_threadpool(self.obligation_reader.get, actor, obligation_id)

    async def assess_message(self, message: str, actor: ActorContext) -> FraudAssessment:
        raise ServiceUnavailable("Fraud assessment is provided by the security service")


class FinanceProposalPort(ProposalPort):
    def __init__(self, intents: IntentService, cases: CaseService) -> None:
        self.intents = intents
        self.cases = cases

    async def create_intent(
        self, proposal: IntentProposal, actor: ActorContext
    ) -> ToolResponse[PaymentIntent]:
        outcome = await run_in_threadpool(self.intents.create, actor, proposal)
        if isinstance(outcome, Created):
            return ToolResponse(data=outcome.intent)
        assert isinstance(outcome, Refused)
        _, error = build_error(outcome.reason_code, outcome.audit_event_id, None)
        return ToolResponse(error=error)

    async def request_approval(self, intent_id: str, actor: ActorContext) -> ApprovalRequest:
        raise ServiceUnavailable("Approval requests are served by the approvals service")

    async def create_case(
        self, submission: CaseSubmission, actor: ActorContext
    ) -> ToolResponse[ReconciliationCase]:
        case = await run_in_threadpool(self.cases.create, actor, submission)
        return ToolResponse(data=case)
