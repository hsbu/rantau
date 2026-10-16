"""Domain ports. Implementations must enforce actor scope on every operation."""

from typing import Protocol

from backend.contracts.models import (
    ActionIntent,
    ActorContext,
    ApprovalRequest,
    CaseSubmission,
    FraudAssessment,
    FxQuote,
    IntentProposal,
    PaymentIntent,
    PaymentResult,
    PermissionSummary,
    PolicyDecision,
    ReconciliationCase,
    ToolResponse,
    TrustedBeneficiary,
    TuitionObligation,
    UniversityPolicy,
)


class AuthorizationPort(Protocol):
    async def evaluate(self, actor: ActorContext, action: ActionIntent) -> PolicyDecision: ...


class PaymentPort(Protocol):
    async def execute(
        self, intent_id: str, idempotency_key: str, actor: ActorContext
    ) -> PaymentResult: ...

    async def status(self, payment_id: str, actor: ActorContext) -> PaymentResult: ...


class UniversityPort(Protocol):
    async def obligation(self, obligation_id: str, actor: ActorContext) -> TuitionObligation: ...

    async def reconcile(self, case_id: str, actor: ActorContext) -> ReconciliationCase:
        """Submit/recheck a case, never approve it or directly post university credit."""
        ...


class AgentReadPort(Protocol):
    """Safe orchestration reads; no payment execution or authority-changing tools."""

    async def obligations(self, actor: ActorContext) -> tuple[TuitionObligation, ...]: ...

    async def policy(self, actor: ActorContext) -> UniversityPolicy: ...

    async def permissions(self, actor: ActorContext) -> tuple[PermissionSummary, ...]: ...

    async def beneficiary(self, beneficiary_id: str, actor: ActorContext) -> TrustedBeneficiary: ...

    async def quotes(self, obligation_id: str, actor: ActorContext) -> tuple[FxQuote, ...]: ...

    async def payment_status(self, payment_id: str, actor: ActorContext) -> PaymentResult: ...

    async def obligation(self, obligation_id: str, actor: ActorContext) -> TuitionObligation: ...

    async def assess_message(self, message: str, actor: ActorContext) -> FraudAssessment: ...


class ProposalPort(Protocol):
    async def create_intent(
        self, proposal: IntentProposal, actor: ActorContext
    ) -> ToolResponse[PaymentIntent]: ...

    async def request_approval(self, intent_id: str, actor: ActorContext) -> ApprovalRequest: ...

    async def create_case(
        self, submission: CaseSubmission, actor: ActorContext
    ) -> ToolResponse[ReconciliationCase]: ...
