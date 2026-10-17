"""Real session and C resource locks for B-06; supports payment-intent aliases."""

from backend.authz.policy_repository import PolicyConnection
from backend.authz.service import AuthService
from backend.contracts.enums import Role
from backend.contracts.models import ActorContext, ScopeDenied
from backend.finance.records import lock_intent, may_view
from backend.fraud.security_cases import SecurityCaseService
from backend.fraud.security_store import SecurityStore


class FinanceResourceAccess:
    def __init__(self, auth: AuthService) -> None:
        self.auth = auth

    def assert_access(
        self, connection: PolicyConnection, actor: ActorContext, resource_id: str
    ) -> None:
        self.auth.current_actor(connection, actor)
        locked = lock_intent(connection, actor.tenant_id, resource_id)
        reviewer = actor.role == Role.DEMO_ADMIN and "security:review" in actor.scopes
        if not reviewer and not may_view(actor.actor_id, locked.intent):
            raise ScopeDenied("Resource unavailable")


def build_security_service(auth: AuthService) -> SecurityCaseService:
    return SecurityCaseService(SecurityStore(FinanceResourceAccess(auth)))
