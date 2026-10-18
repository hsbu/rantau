"""Use stored owner authority for protected finance execution, never a preview."""

from backend.approvals.finance import FinanceApprovalRepository
from backend.approvals.service import ApprovalService
from backend.authz.policy_repository import PolicyConnection
from backend.authz.policy_transaction import TransactionAuthorization
from backend.authz.service import AuthService
from backend.contracts.models import ActionIntent, ActorContext, PolicyDecision


def build_approval_service(auth: AuthService, ttl_seconds: int = 600) -> ApprovalService:
    return ApprovalService(auth, FinanceApprovalRepository(auth), ttl_seconds)


class ProtectedAuthorization:
    def __init__(self, connection: PolicyConnection, service: ApprovalService) -> None:
        self.connection, self.service = connection, service

    async def evaluate(self, actor: ActorContext, action: ActionIntent) -> PolicyDecision:
        if action.action == "EXECUTE_PAYMENT":
            return await self.service.authorize_execution(self.connection, actor, action)
        return await TransactionAuthorization(
            self.connection, self.service.auth, self.service.finance
        ).evaluate(actor, action)
