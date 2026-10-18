"""B advisory assessment composed with the existing scoped domain read port."""

from starlette.concurrency import run_in_threadpool

from backend.authz.service import AuthService
from backend.contracts.enums import Role
from backend.contracts.models import (
    ActorContext,
    FraudAssessment,
    FxQuote,
    PaymentResult,
    PermissionSummary,
    ScopeDenied,
    TrustedBeneficiary,
    TuitionObligation,
    UniversityPolicy,
)
from backend.contracts.ports import AgentReadPort
from backend.fraud.assessment import FraudAssessor


class SecurityAgentReadPort(AgentReadPort):
    """No financial authority: domain reads retain their existing authorization guards."""

    def __init__(
        self, delegate: AgentReadPort, auth: AuthService, assessor: FraudAssessor
    ) -> None:
        self.delegate = delegate
        self.auth = auth
        self.assessor = assessor

    def _require_current(self, actor: ActorContext) -> None:
        with self.auth.database.connection() as connection:
            self.auth.current_actor(connection, actor)
            if actor.role != Role.STUDENT or "student:read" not in actor.scopes:
                raise ScopeDenied("Resource unavailable")

    async def assess_message(self, message: str, actor: ActorContext) -> FraudAssessment:
        await run_in_threadpool(self._require_current, actor)
        assessment = await self.assessor.assess_advisory(message)
        await run_in_threadpool(self._require_current, actor)
        return assessment

    async def obligations(self, actor: ActorContext) -> tuple[TuitionObligation, ...]:
        return await self.delegate.obligations(actor)

    async def policy(self, actor: ActorContext) -> UniversityPolicy:
        return await self.delegate.policy(actor)

    async def permissions(self, actor: ActorContext) -> tuple[PermissionSummary, ...]:
        return await self.delegate.permissions(actor)

    async def beneficiary(self, beneficiary_id: str, actor: ActorContext) -> TrustedBeneficiary:
        return await self.delegate.beneficiary(beneficiary_id, actor)

    async def quotes(self, obligation_id: str, actor: ActorContext) -> tuple[FxQuote, ...]:
        return await self.delegate.quotes(obligation_id, actor)

    async def payment_status(self, payment_id: str, actor: ActorContext) -> PaymentResult:
        return await self.delegate.payment_status(payment_id, actor)

    async def obligation(self, obligation_id: str, actor: ActorContext) -> TuitionObligation:
        return await self.delegate.obligation(obligation_id, actor)
