"""Deterministic policy only. No DB writes, model calls or financial effects."""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.authz.policy_models import PaymentSnapshot, ReconciliationSnapshot
from backend.contracts.enums import (
    ApprovalState,
    Decision,
    PaymentState,
    ReasonCode,
    Role,
    Tier,
    TuitionState,
)
from backend.contracts.models import ActionIntent, ActorContext, PaymentTerms, ServiceUnavailable


@dataclass(frozen=True)
class PolicyOutcome:
    decision: Decision
    tier: Tier
    reason_code: ReasonCode | None = None


def _out(decision: Decision, tier: Tier, reason: ReasonCode) -> PolicyOutcome:
    return PolicyOutcome(decision, tier, reason)


def _spending(snapshot: PaymentSnapshot, now: datetime) -> tuple[int, int, int, bool]:
    """Exclude the candidate once from period totals and recover only its reserve."""
    account, intent = snapshot.account, snapshot.intent
    today = now.astimezone(ZoneInfo(account.timezone)).date()
    month = today.replace(day=1)
    if snapshot.spending_day != today or snapshot.spending_month != month:
        raise ServiceUnavailable("Current spending data unavailable")
    daily = monthly = own_reservation = 0
    completed = False
    seen: set[str] = set()
    for entry in snapshot.spending:
        if (
            entry.intent_id in seen
            or entry.account_id != account.id
            or entry.currency != account.currency
            or entry.at > now
        ):
            raise ServiceUnavailable("Current spending data unavailable")
        seen.add(entry.intent_id)
        if entry.intent_id == intent.id:
            if entry.state == "COMPLETED":
                completed = True
            elif entry.amount_minor != intent.source_total_minor:
                raise ServiceUnavailable("Current reservation terms unavailable")
            else:
                own_reservation = entry.amount_minor
            continue
        local_day = entry.at.astimezone(ZoneInfo(account.timezone)).date()
        if local_day == today:
            daily += entry.amount_minor
        if local_day.replace(day=1) == month:
            monthly += entry.amount_minor
    return daily, monthly, own_reservation, completed


def _mandate_eligible(
    actor: ActorContext, snapshot: PaymentSnapshot, now: datetime, daily: int, monthly: int
) -> bool:
    mandate, intent = snapshot.mandate, snapshot.intent
    return bool(
        mandate is not None
        and not mandate.revoked
        and mandate.starts_at <= now < mandate.expires_at
        and mandate.owner_id == intent.funding_owner_id
        and mandate.delegate_id == actor.actor_id
        and mandate.account_id == intent.source_account_id
        and mandate.beneficiary_id == intent.beneficiary_id
        and mandate.beneficiary_fingerprint == intent.beneficiary_fingerprint
        and mandate.currency == intent.source_currency
        and mandate.purpose == intent.purpose == "ALLOWANCE"
        and intent.source_total_minor <= mandate.per_transfer_limit_minor
        and daily + intent.source_total_minor <= mandate.daily_limit_minor
        and monthly + intent.source_total_minor <= mandate.monthly_limit_minor
    )


def evaluate_payment(
    actor: ActorContext, action: ActionIntent, snapshot: PaymentSnapshot, now: datetime
) -> PolicyOutcome:
    """Evaluate trusted current facts; this result alone authorizes no later debit."""
    intent, account, rules = snapshot.intent, snapshot.account, snapshot.rules
    scope = {"CREATE_INTENT": "payment:propose", "EXECUTE_PAYMENT": "payment:execute"}.get(
        action.action
    )

    def deny(reason: ReasonCode, tier: Tier = Tier.T3) -> PolicyOutcome:
        return _out(Decision.DENY, tier, reason)

    if (
        scope is None
        or scope not in actor.scopes
        or actor.role not in {Role.STUDENT, Role.SPONSOR}
        or actor.tenant_id != snapshot.tenant_id
        or account.tenant_id != snapshot.tenant_id
        or actor.actor_id not in snapshot.authorized_requesters
        or intent.requested_by not in snapshot.authorized_requesters
        or action.resource_id != intent.id
        or account.id != intent.source_account_id
        or account.owner_id != intent.funding_owner_id
        or account.currency != intent.source_currency
        or not account.active
        or not account.owner_active
    ):
        return deny(ReasonCode.INVALID_SCOPE)
    if now.utcoffset() is None:
        raise ServiceUnavailable("Current policy clock unavailable")
    if intent.state == PaymentState.OUTCOME_UNKNOWN:
        return deny(ReasonCode.PROVIDER_OUTCOME_UNKNOWN)
    if intent.state in {PaymentState.PROCESSING, PaymentState.DELIVERED}:
        return deny(ReasonCode.PAYMENT_ALREADY_SUBMITTED)
    if intent.state in {
        PaymentState.FAILED,
        PaymentState.REJECTED,
        PaymentState.EXPIRED,
        PaymentState.CANCELLED,
    }:
        return deny(ReasonCode.INVALID_SCOPE)
    if (
        snapshot.held
        or snapshot.risk_floor == Tier.T3
        or intent.tier == Tier.T3
        or intent.state == PaymentState.ON_HOLD
    ):
        return _out(Decision.HOLD, Tier.T3, ReasonCode.SECURITY_HOLD)
    beneficiary = snapshot.beneficiary
    if not beneficiary.verified:
        return _out(Decision.HOLD, Tier.T3, ReasonCode.UNKNOWN_BENEFICIARY)
    if (
        beneficiary.id != intent.beneficiary_id
        or beneficiary.fingerprint != intent.beneficiary_fingerprint
        or beneficiary.owner_id != snapshot.recipient_owner_id
    ):
        return _out(Decision.HOLD, Tier.T3, ReasonCode.BENEFICIARY_MISMATCH)
    if action.terms_hash != intent.terms_hash:
        return _out(Decision.REQUIRE_APPROVAL, Tier.T2, ReasonCode.APPROVAL_TERMS_MISMATCH)
    if not rules.effective_from <= now < rules.effective_to:
        return _out(Decision.HOLD, Tier.T3, ReasonCode.SECURITY_HOLD)
    if (
        intent.purpose not in rules.purposes
        or (intent.source_currency, intent.destination_currency) not in rules.currency_pairs
    ):
        return deny(ReasonCode.INVALID_SCOPE)
    if rules.version != intent.policy_version:
        return _out(Decision.HOLD, Tier.T3, ReasonCode.SECURITY_HOLD)
    daily, monthly, own_reservation, completed = _spending(snapshot, now)
    if completed:
        return deny(ReasonCode.PAYMENT_ALREADY_SUBMITTED)
    amount = intent.source_total_minor
    routine = (
        intent.purpose == "ALLOWANCE"
        and intent.intent_revision == 1
        and amount <= rules.routine_threshold_minor
        and _mandate_eligible(actor, snapshot, now, daily, monthly)
    )
    tier = max(Tier.T1 if routine else Tier.T2, snapshot.risk_floor, intent.tier)
    quote = snapshot.quote
    if now >= quote.expires_at or now >= intent.quote_expiry:
        return deny(ReasonCode.QUOTE_EXPIRED, tier)
    if (
        quote.id != intent.quote_id
        or quote.expires_at != intent.quote_expiry
        or quote.source_currency != intent.source_currency
        or quote.destination_currency != intent.destination_currency
        or quote.source_total_minor != intent.source_total_minor
        or quote.destination_amount_minor != intent.destination_amount_minor
    ):
        return _out(Decision.HOLD, Tier.T3, ReasonCode.SECURITY_HOLD)
    if intent.purpose == "TUITION":
        obligation, policy = snapshot.obligation, snapshot.university_policy
        if (
            obligation is None
            or policy is None
            or not policy.usable_at(now)
            or obligation.id != intent.obligation_id
            or obligation.policy_id != policy.id
            or obligation.student_id not in snapshot.authorized_requesters
            or obligation.university_id != policy.university_id
            or beneficiary.owner_id != obligation.university_id
            or policy.version != intent.policy_version
            or obligation.currency != intent.destination_currency
        ):
            return _out(Decision.HOLD, Tier.T3, ReasonCode.UNIVERSITY_POLICY_UNKNOWN)
        if obligation.state == TuitionState.AWAITING_POSTING:
            return _out(Decision.HOLD, tier, ReasonCode.POSTING_WINDOW_ACTIVE)
        if obligation.state in {
            TuitionState.EXCEPTION,
            TuitionState.RECONCILIATION_PENDING,
            TuitionState.ESCALATED,
        }:
            return _out(Decision.HOLD, tier, ReasonCode.RECONCILIATION_NEEDS_INFO)
        if obligation.state == TuitionState.PAID:
            return deny(ReasonCode.PAYMENT_ALREADY_SUBMITTED, tier)
        if obligation.posted_minor > 0 and (
            not policy.topup_allowed or intent.destination_amount_minor != obligation.balance_minor
        ):
            return deny(ReasonCode.TOPUP_NOT_PERMITTED, tier)
        if intent.destination_amount_minor > obligation.balance_minor or (
            intent.destination_amount_minor < obligation.balance_minor
            and not policy.partial_payment_allowed
        ):
            return deny(ReasonCode.INVALID_SCOPE, tier)
    if amount > account.available_minor + own_reservation:
        return deny(ReasonCode.INSUFFICIENT_FUNDS, tier)
    if (
        amount > account.per_transfer_limit_minor
        or daily + amount > account.daily_limit_minor
        or monthly + amount > account.monthly_limit_minor
    ):
        return deny(ReasonCode.LIMIT_EXCEEDED, tier)
    if tier == Tier.T1:
        return PolicyOutcome(Decision.ALLOW, tier)
    approval = snapshot.approval
    if approval is None:
        return _out(Decision.REQUIRE_APPROVAL, tier, ReasonCode.FUNDING_OWNER_APPROVAL_REQUIRED)
    if any(
        getattr(approval, field) != getattr(intent, field) for field in PaymentTerms.model_fields
    ):
        return _out(Decision.REQUIRE_APPROVAL, tier, ReasonCode.APPROVAL_TERMS_MISMATCH)
    if approval.expires_at <= now or approval.state == ApprovalState.EXPIRED:
        return _out(Decision.REQUIRE_APPROVAL, tier, ReasonCode.APPROVAL_EXPIRED)
    if (
        approval.approver_actor_id != account.owner_id
        or approval.state != ApprovalState.APPROVED
        or approval.consumed_at is not None
    ):
        return _out(Decision.REQUIRE_APPROVAL, tier, ReasonCode.FUNDING_OWNER_APPROVAL_REQUIRED)
    return PolicyOutcome(Decision.ALLOW, tier)


def evaluate_reconciliation(
    actor: ActorContext, action: ActionIntent, snapshot: ReconciliationSnapshot
) -> PolicyOutcome:
    if (
        action.action != "SUBMIT_RECONCILIATION"
        or "reconciliation:submit" not in actor.scopes
        or actor.role != Role.STUDENT
        or actor.tenant_id != snapshot.tenant_id
        or actor.actor_id != snapshot.student_id
        or action.resource_id != snapshot.case_id
        or not snapshot.submission_allowed
    ):
        return _out(Decision.DENY, Tier.T3, ReasonCode.INVALID_SCOPE)
    # A scoped evidence submission is state-changing but never financial approval.
    return PolicyOutcome(Decision.ALLOW, Tier.T2)
