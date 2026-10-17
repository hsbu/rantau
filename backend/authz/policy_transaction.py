"""Transaction-bound AuthorizationPort; no executor, ledger changes or auto-commit."""

from uuid import uuid4

import psycopg
from psycopg.pq import TransactionStatus

from backend.authz.policy import PolicyOutcome, evaluate_payment, evaluate_reconciliation
from backend.authz.policy_models import PaymentSnapshot, ReconciliationSnapshot
from backend.authz.policy_repository import PolicyConnection, PolicyRepository
from backend.authz.service import AuthService
from backend.contracts.enums import Decision, ReasonCode, Role, Tier
from backend.contracts.models import (
    ActionIntent,
    ActorContext,
    PolicyDecision,
    ScopeDenied,
    ServiceUnavailable,
)
from backend.contracts.ports import AuthorizationPort

_ACTION_SCOPES = {
    "CREATE_INTENT": "payment:propose",
    "EXECUTE_PAYMENT": "payment:execute",
    "SUBMIT_RECONCILIATION": "reconciliation:submit",
}


class TransactionAuthorization(AuthorizationPort):
    """Call inside C's protected transaction, on its connection and worker thread.

    The async signature implements the established AuthorizationPort. This adapter
    performs synchronous psycopg work; callers must not run it on an ASGI event
    loop. It neither commits nor opens another connection. C must atomically
    consume authority, reserve and debit before committing an ALLOW; no preview
    result may be reused. Commit non-ALLOW attempts without a debit to preserve
    their audit. On rollback/exception no durable audit or authorization exists.
    """

    def __init__(
        self,
        connection: PolicyConnection,
        auth_service: AuthService,
        repository: PolicyRepository | None,
    ) -> None:
        self.connection = connection
        self.auth_service = auth_service
        self.repository = repository

    async def evaluate(self, actor: ActorContext, action: ActionIntent) -> PolicyDecision:
        connection = self.connection
        if (
            self.repository is None
            or connection.closed
            or connection.autocommit
            or connection.info.transaction_status
            not in {TransactionStatus.IDLE, TransactionStatus.INTRANS}
        ):
            raise ServiceUnavailable("Trusted authorization transaction unavailable")
        try:
            self.auth_service.current_actor(connection, actor)
            resource_id: str | None = None
            if (
                _ACTION_SCOPES[action.action] not in actor.scopes
                or actor.role not in {Role.STUDENT, Role.SPONSOR}
                or (action.action == "SUBMIT_RECONCILIATION" and actor.role != Role.STUDENT)
            ):
                outcome = PolicyOutcome(Decision.DENY, Tier.T3, ReasonCode.INVALID_SCOPE)
            else:
                outcome, resource_id = self._load_and_evaluate(actor, action)
            # Recheck expiry after potentially waiting for financial locks.
            self.auth_service.current_actor(connection, actor)
            audit_id = "audit_" + uuid4().hex
            connection.execute(
                "INSERT INTO policy_decisions "
                "(audit_event_id, tenant_id, actor_id, action, resource_id, "
                "decision, tier, reason_code) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    audit_id,
                    actor.tenant_id,
                    actor.actor_id,
                    action.action,
                    resource_id,
                    outcome.decision.value,
                    outcome.tier.value,
                    outcome.reason_code.value if outcome.reason_code else None,
                ),
            )
            return PolicyDecision(
                decision=outcome.decision,
                tier=outcome.tier,
                reason_code=outcome.reason_code,
                audit_event_id=audit_id,
            )
        except psycopg.Error:
            raise ServiceUnavailable("Authorization storage unavailable") from None

    def _load_and_evaluate(
        self, actor: ActorContext, action: ActionIntent
    ) -> tuple[PolicyOutcome, str | None]:
        assert self.repository is not None
        resource_id: str | None
        try:
            if action.action == "SUBMIT_RECONCILIATION":
                case = self.repository.load_reconciliation(self.connection, actor, action)
                if not isinstance(case, ReconciliationSnapshot):
                    raise ServiceUnavailable("Trusted reconciliation data unavailable")
                outcome = evaluate_reconciliation(actor, action, case)
                resource_id = case.case_id
            else:
                payment = self.repository.load_payment(self.connection, actor, action)
                if not isinstance(payment, PaymentSnapshot):
                    raise ServiceUnavailable("Trusted financial data unavailable")
                # clock_timestamp(), unlike now(), advances within a transaction.
                clock = self.connection.execute("SELECT clock_timestamp() AS now").fetchone()
                assert clock is not None
                outcome = evaluate_payment(actor, action, payment, clock["now"])
                resource_id = payment.intent.id
            if outcome.reason_code == ReasonCode.INVALID_SCOPE:
                resource_id = None
            return outcome, resource_id
        except ScopeDenied:
            return PolicyOutcome(Decision.DENY, Tier.T3, ReasonCode.INVALID_SCOPE), None
        except Exception:
            # Repository exceptions can contain DSNs, account data or raw records.
            raise ServiceUnavailable("Trusted authorization data unavailable") from None
