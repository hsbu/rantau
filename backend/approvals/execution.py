"""Real stored B authority + real B-02 gate, inside C's protected transaction."""

from typing import TYPE_CHECKING

from backend.approvals.repository import ApprovalFinanceRepository
from backend.approvals.store import AuthorityStore, database_time, terms_of
from backend.authz.policy import evaluate_payment
from backend.authz.policy_models import PaymentSnapshot, ReconciliationSnapshot
from backend.authz.policy_repository import PolicyConnection, PolicyRepository
from backend.authz.policy_transaction import TransactionAuthorization
from backend.contracts.enums import Decision, Tier
from backend.contracts.models import (
    ActionIntent,
    ActorContext,
    PolicyDecision,
    ScopeDenied,
    ServiceUnavailable,
)

if TYPE_CHECKING:
    from backend.approvals.service import ApprovalService


class AuthorityRepository(PolicyRepository):
    def __init__(self, finance: ApprovalFinanceRepository) -> None:
        self.finance = finance
        self.payment: PaymentSnapshot | None = None

    def load_payment(
        self, connection: PolicyConnection, actor: ActorContext, action: ActionIntent
    ) -> PaymentSnapshot:
        from backend.contracts.terms import canonical_terms_hash

        payment = self.finance.load_payment(connection, actor, action)
        if (
            payment.tenant_id != actor.tenant_id
            or payment.account.tenant_id != actor.tenant_id
            or payment.intent.id != action.resource_id
            or actor.actor_id not in payment.authorized_requesters
            or actor.actor_id not in {payment.intent.requested_by, payment.account.owner_id}
            or payment.account.owner_id != payment.intent.funding_owner_id
            or payment.account.id != payment.intent.source_account_id
        ):
            raise ScopeDenied()
        terms = terms_of(payment.intent)
        if canonical_terms_hash(terms) != terms.terms_hash:
            raise ServiceUnavailable("Trusted current terms unavailable")
        store = AuthorityStore(connection)
        records = store.refresh(actor, terms)
        approval = store.approval(records[0]) if records else None
        mandate = store.mandate_for_payment(
            actor, payment.account.id, payment.beneficiary.id, payment.account.timezone
        )
        self.payment = payment.model_copy(update={"approval": approval, "mandate": mandate})
        return self.payment

    def load_reconciliation(
        self, connection: PolicyConnection, actor: ActorContext, action: ActionIntent
    ) -> ReconciliationSnapshot:
        return self.finance.load_reconciliation(connection, actor, action)


async def authorize_execution(
    connection: PolicyConnection,
    service: "ApprovalService",
    actor: ActorContext,
    action: ActionIntent,
) -> PolicyDecision:
    from backend.approvals.service import ApprovalConflict

    if connection.autocommit or connection.closed or service.finance is None:
        raise ServiceUnavailable("Protected authority transaction unavailable")
    if action.action != "EXECUTE_PAYMENT":
        raise ApprovalConflict("EXECUTION_ACTION_REQUIRED")
    # Start the caller-owned transaction before the savepoint. The nested block
    # may never commit an IDLE connection's transaction behind the caller's back.
    service.auth.current_actor(connection, actor)
    repository = AuthorityRepository(service.finance)
    with connection.transaction():
        result = await TransactionAuthorization(connection, service.auth, repository).evaluate(
            actor, action
        )
        if result.decision != Decision.ALLOW:
            return result
        snapshot = repository.payment
        assert snapshot is not None
        if result.tier == Tier.T2:
            approval = snapshot.approval
            assert approval is not None
            row = connection.execute(
                "UPDATE approvals SET state = 'CONSUMED', consumed_at = clock_timestamp() "
                "WHERE tenant_id = %s AND approval_id = %s AND state = 'APPROVED' "
                "AND owner_id = %s AND terms_hash = %s AND terms = %s::jsonb "
                "AND expires_at > clock_timestamp() RETURNING approval_id",
                (
                    actor.tenant_id,
                    approval.id,
                    snapshot.account.owner_id,
                    snapshot.intent.terms_hash,
                    terms_of(snapshot.intent).model_dump_json(),
                ),
            ).fetchone()
            if row is None:
                raise ApprovalConflict("AUTHORITY_NOT_CURRENT")
            AuthorityStore(connection).event(actor, "APPROVAL_CONSUMED", approval.id, "CONSUMED")
        service.auth.current_actor(connection, actor)
        # Locks protect these facts from other writers, but time still advances
        # during audit/session queries. Reject late expiry inside this savepoint
        # so neither consumption nor an ALLOW audit survives a stale result.
        fresh = evaluate_payment(actor, action, snapshot, database_time(connection))
        if fresh.decision != Decision.ALLOW or fresh.tier != result.tier:
            raise ApprovalConflict("AUTHORITY_NOT_CURRENT")
        # C must now reserve limits/create transfer/debit on THIS connection,
        # retaining all locks and checking freshness at its financial mutation.
        # A preview/reused result cannot authorize payment.
        return result
