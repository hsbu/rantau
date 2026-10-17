"""Test-only stand-in for Dev B's approval, mandate and hold stores (B-03/B-06 are not built)."""

from dataclasses import dataclass, field
from datetime import timedelta

from backend.authz.policy_models import MandateSnapshot
from backend.contracts.enums import ApprovalState, Tier
from backend.contracts.models import Approval, PaymentIntent, PaymentTerms
from backend.finance.authority import HoldState
from backend.finance.clock import db_now


@dataclass
class ScriptedAuthority:
    approved: set[str] = field(default_factory=set)
    held: bool = False
    risk_floor: Tier = Tier.T0
    # (per transfer, daily, monthly) caps of a scripted allowance mandate; None means no mandate
    mandate_limits: tuple[int, int, int] | None = None

    def approval(self, connection, intent: PaymentIntent) -> Approval | None:  # type: ignore[no-untyped-def]
        if intent.id not in self.approved:
            return None
        terms = {name: getattr(intent, name) for name in PaymentTerms.model_fields}
        return Approval(
            **terms,
            id="approval_test",
            approver_actor_id=intent.funding_owner_id,
            expires_at=db_now(connection) + timedelta(minutes=10),
            state=ApprovalState.APPROVED,
        )

    def mandate(self, connection, intent: PaymentIntent) -> MandateSnapshot | None:  # type: ignore[no-untyped-def]
        if self.mandate_limits is None:
            return None
        per_transfer, daily, monthly = self.mandate_limits
        now = db_now(connection)
        return MandateSnapshot(
            id="mandate_test",
            owner_id=intent.funding_owner_id,
            delegate_id=intent.requested_by,
            account_id=intent.source_account_id,
            beneficiary_id=intent.beneficiary_id,
            beneficiary_fingerprint=intent.beneficiary_fingerprint,
            currency=intent.source_currency,
            purpose="ALLOWANCE",
            per_transfer_limit_minor=per_transfer,
            daily_limit_minor=daily,
            monthly_limit_minor=monthly,
            starts_at=now - timedelta(days=1),
            expires_at=now + timedelta(days=30),
            revoked=False,
        )

    def hold(self, connection, intent: PaymentIntent) -> HoldState:  # type: ignore[no-untyped-def]
        return HoldState(held=self.held, risk_floor=self.risk_floor)
