"""Trusted financial inputs for tests only; never imported by application wiring."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from backend.authz.policy_models import (
    AccountSnapshot,
    MandateSnapshot,
    PaymentSnapshot,
    PolicyRules,
)
from backend.contracts.enums import Currency, PaymentState, Tier
from backend.contracts.models import ActionIntent, Approval, PaymentTerms, TrustedBeneficiary
from tests.fixtures.data import ACTOR, INTENT, NOW, OBLIGATION, POLICY, QUOTE

ACTOR_EXECUTOR = ACTOR.model_copy(
    update={"scopes": ACTOR.scopes | {"payment:execute", "reconciliation:submit"}}
)
ACTION = ActionIntent(action="EXECUTE_PAYMENT", resource_id=INTENT.id, terms_hash=INTENT.terms_hash)


def tuition():
    return PaymentSnapshot(
        tenant_id=ACTOR.tenant_id,
        intent=INTENT,
        account=AccountSnapshot(
            id=INTENT.source_account_id,
            tenant_id=ACTOR.tenant_id,
            owner_id=INTENT.funding_owner_id,
            active=True,
            owner_active=True,
            currency=Currency.IDR,
            timezone="Asia/Jakarta",
            available_minor=100_000_000,
            per_transfer_limit_minor=200_000_000,
            daily_limit_minor=300_000_000,
            monthly_limit_minor=500_000_000,
        ),
        authorized_requesters=frozenset({ACTOR.actor_id, INTENT.funding_owner_id}),
        beneficiary=TrustedBeneficiary(
            id=INTENT.beneficiary_id,
            owner_id=OBLIGATION.university_id,
            masked_display="Synthetic university ***001",
            fingerprint=INTENT.beneficiary_fingerprint,
            verified=True,
        ),
        recipient_owner_id=OBLIGATION.university_id,
        quote=QUOTE,
        rules=PolicyRules(
            version=INTENT.policy_version,
            effective_from=NOW - timedelta(days=1),
            effective_to=NOW + timedelta(days=60),
            routine_threshold_minor=50_000_000,
            purposes=frozenset({"TUITION", "ALLOWANCE"}),
            currency_pairs=frozenset({(Currency.IDR, Currency.CNY)}),
        ),
        spending=(),
        mandate=None,
        approval=None,
        held=False,
        risk_floor=Tier.T0,
        obligation=OBLIGATION,
        university_policy=POLICY,
        spending_day=NOW.astimezone(ZoneInfo("Asia/Jakarta")).date(),
        spending_month=NOW.date().replace(day=1),
    )


def approve(snapshot, **updates):
    fields = {key: getattr(snapshot.intent, key) for key in PaymentTerms.model_fields}
    approval = Approval(
        **fields,
        id="approval_test",
        approver_actor_id=snapshot.account.owner_id,
        expires_at=NOW + timedelta(minutes=10),
        state="APPROVED",
    )
    return snapshot.model_copy(update={"approval": approval.model_copy(update=updates)})


def allowance():
    snapshot = tuition()
    intent = snapshot.intent.model_copy(
        update={
            "purpose": "ALLOWANCE",
            "obligation_id": None,
            "tier": Tier.T1,
            "state": PaymentState.DRAFT,
        }
    )
    mandate = MandateSnapshot(
        id="mandate_test",
        owner_id=intent.funding_owner_id,
        delegate_id=ACTOR.actor_id,
        account_id=intent.source_account_id,
        beneficiary_id=intent.beneficiary_id,
        beneficiary_fingerprint=intent.beneficiary_fingerprint,
        currency=intent.source_currency,
        purpose="ALLOWANCE",
        per_transfer_limit_minor=50_000_000,
        daily_limit_minor=100_000_000,
        monthly_limit_minor=150_000_000,
        starts_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=30),
        revoked=False,
    )
    return snapshot.model_copy(update={"intent": intent, "mandate": mandate})
