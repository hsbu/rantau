"""Explicit test-only fakes. Application wiring must never import this module."""

from backend.contracts.enums import CaseState, Decision, ReasonCode, Tier
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
    ScopeDenied,
    ServiceUnavailable,
    ToolResponse,
    TrustedBeneficiary,
    TuitionObligation,
    UniversityPolicy,
)
from backend.contracts.ports import (
    AgentReadPort,
    AuthorizationPort,
    PaymentPort,
    ProposalPort,
    UniversityPort,
)
from tests.fixtures.data import ACTOR, INTENT, OBLIGATION, PAYMENT, POLICY, QUOTE, QUOTE_B


def scoped(actor: ActorContext) -> None:
    if actor != ACTOR:
        raise ScopeDenied("Resource unavailable")


class FakeAuthorizationPort(AuthorizationPort):
    async def evaluate(self, actor: ActorContext, action: ActionIntent) -> PolicyDecision:
        scoped(actor)
        return PolicyDecision(
            decision=Decision.REQUIRE_APPROVAL,
            tier=Tier.T2,
            reason_code=ReasonCode.FUNDING_OWNER_APPROVAL_REQUIRED,
            audit_event_id="audit_fake",
        )


class FakePaymentPort(PaymentPort):
    async def execute(
        self, intent_id: str, idempotency_key: str, actor: ActorContext
    ) -> PaymentResult:
        scoped(actor)
        # No fake sponsor approval, debit, financial ledger or successful execution.
        raise ServiceUnavailable("Execution requires trusted authorization and finance services")

    async def status(self, payment_id: str, actor: ActorContext) -> PaymentResult:
        scoped(actor)
        if payment_id != PAYMENT.payment_id:
            raise ScopeDenied("Resource unavailable")
        return PAYMENT


class FakeUniversityPort(UniversityPort):
    async def obligation(self, obligation_id: str, actor: ActorContext) -> TuitionObligation:
        scoped(actor)
        if obligation_id != OBLIGATION.id:
            raise ScopeDenied("Resource unavailable")
        return OBLIGATION

    async def reconcile(self, case_id: str, actor: ActorContext) -> ReconciliationCase:
        scoped(actor)
        return ReconciliationCase(
            id=case_id,
            payment_id=PAYMENT.payment_id,
            obligation_id=OBLIGATION.id,
            evidence_ids=(),
            evidence_missing=("receipt",),
            state=CaseState.NEEDS_INFO,
            audit_event_id="audit_fake_case",
        )


class FakeReadPort(AgentReadPort):
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.payment = PAYMENT
        self.tuition = OBLIGATION
        self.rules = POLICY

    def check(self, actor: ActorContext, operation: str) -> None:
        scoped(actor)
        self.calls.append(operation)

    async def obligations(self, actor: ActorContext) -> tuple[TuitionObligation, ...]:
        self.check(actor, "obligations")
        return (self.tuition,)

    async def policy(self, actor: ActorContext) -> UniversityPolicy:
        self.check(actor, "policy")
        return self.rules

    async def permissions(self, actor: ActorContext) -> tuple[PermissionSummary, ...]:
        self.check(actor, "permissions")
        return (
            PermissionSummary(
                account_id="acct_idr_01",
                owner_id="par_001",
                permitted_purposes=("TUITION", "ALLOWANCE"),
                approval_required=True,
            ),
        )

    async def beneficiary(self, beneficiary_id: str, actor: ActorContext) -> TrustedBeneficiary:
        self.check(actor, "beneficiary")
        if beneficiary_id != "benef_uni_cn_01":
            raise ScopeDenied("Resource unavailable")
        return TrustedBeneficiary(
            id=beneficiary_id,
            owner_id="uni_cn_01",
            masked_display="Fictional university •••• DEMO",
            fingerprint="synthetic-fingerprint",
            verified=True,
        )

    async def quotes(self, obligation_id: str, actor: ActorContext) -> tuple[FxQuote, ...]:
        await self.obligation(obligation_id, actor)
        self.calls.append("quotes")
        return (QUOTE, QUOTE_B)

    async def payment_status(self, payment_id: str, actor: ActorContext) -> PaymentResult:
        self.check(actor, "payment_status")
        if payment_id != self.payment.payment_id:
            raise ScopeDenied("Resource unavailable")
        return self.payment

    async def obligation(self, obligation_id: str, actor: ActorContext) -> TuitionObligation:
        self.check(actor, "obligation")
        if obligation_id != self.tuition.id:
            raise ScopeDenied("Resource unavailable")
        return self.tuition

    async def assess_message(self, message: str, actor: ActorContext) -> FraudAssessment:
        self.check(actor, "assess_message")
        return FraudAssessment(indicators=("UNTRUSTED_MESSAGE",), next_action="REVIEW_REQUIRED")


class FakeProposalPort(ProposalPort):
    async def create_intent(
        self, proposal: IntentProposal, actor: ActorContext
    ) -> ToolResponse[PaymentIntent]:
        scoped(actor)
        return ToolResponse(data=INTENT)

    async def request_approval(self, intent_id: str, actor: ActorContext) -> ApprovalRequest:
        scoped(actor)
        if intent_id != INTENT.id:
            raise ScopeDenied("Resource unavailable")
        return ApprovalRequest(approval_id="approval_requested_001", intent_id=intent_id)

    async def create_case(
        self, submission: CaseSubmission, actor: ActorContext
    ) -> ToolResponse[ReconciliationCase]:
        scoped(actor)
        return ToolResponse(
            data=ReconciliationCase(
                id="case_001",
                payment_id=submission.payment_id,
                obligation_id=submission.obligation_id,
                evidence_ids=submission.evidence_ids,
                evidence_missing=(),
                state=CaseState.SUBMITTED,
                audit_event_id="audit_case",
            )
        )
