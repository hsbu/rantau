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
        return None

    def hold(self, connection, intent: PaymentIntent) -> HoldState:  # type: ignore[no-untyped-def]
        return HoldState(held=self.held, risk_floor=self.risk_floor)
