"""Veto late expiry after financial writes, before C commits the same transaction."""

from backend.approvals.service import ApprovalConflict, ApprovalService
from backend.approvals.store import database_time, terms_of
from backend.authz.policy_repository import PolicyConnection
from backend.contracts.enums import ApprovalState, Tier
from backend.contracts.models import ActionIntent, ActorContext, PolicyDecision
from backend.finance.records import LockedIntent, intent_from_row


def finalize_execution(
    service: ApprovalService,
    connection: PolicyConnection,
    actor: ActorContext,
    locked: LockedIntent,
    decision: PolicyDecision,
) -> None:
    """This check only rejects; it cannot issue or reuse financial authorization.

    The protected gate already consumed T2 authority in this transaction. C has
    written its ledger, but nothing is committed or sent to the provider yet.
    Keep the account/resource/trust/authority locks through this final check.
    """
    assert service.finance is not None
    intent = intent_from_row(locked.intent)
    snapshot = service.finance.load_payment(
        connection,
        actor,
        ActionIntent(action="EXECUTE_PAYMENT", resource_id=intent.id, terms_hash=intent.terms_hash),
    )
    service.auth.current_actor(connection, actor)
    now = database_time(connection)
    if (
        terms_of(snapshot.intent) != terms_of(intent)
        or snapshot.held
        or snapshot.risk_floor == Tier.T3
        or not snapshot.account.active
        or not snapshot.account.owner_active
        or not snapshot.beneficiary.verified
        or snapshot.beneficiary.fingerprint != intent.beneficiary_fingerprint
        or snapshot.quote.expires_at <= now
        or intent.quote_expiry <= now
        or not snapshot.rules.effective_from <= now < snapshot.rules.effective_to
        or (
            intent.purpose == "TUITION"
            and (
                snapshot.university_policy is None or not snapshot.university_policy.usable_at(now)
            )
        )
    ):
        raise ApprovalConflict("AUTHORITY_NOT_CURRENT")
    if decision.tier == Tier.T2:
        approval = snapshot.approval
        if (
            approval is None
            or approval.state != ApprovalState.CONSUMED
            or approval.consumed_at is None
            or approval.expires_at <= now
            or approval.approver_actor_id != intent.funding_owner_id
            or terms_of(approval) != terms_of(intent)
        ):
            raise ApprovalConflict("AUTHORITY_NOT_CURRENT")
    elif decision.tier == Tier.T1:
        mandate = snapshot.mandate
        if mandate is None or mandate.revoked or not mandate.starts_at <= now < mandate.expires_at:
            raise ApprovalConflict("AUTHORITY_NOT_CURRENT")
