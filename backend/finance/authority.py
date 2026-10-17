"""Seam for Dev B's approval, mandate and hold stores; absence must fail closed."""

from dataclasses import dataclass
from typing import Protocol

from backend.authz.policy_models import MandateSnapshot
from backend.authz.policy_repository import PolicyConnection
from backend.contracts.enums import Tier
from backend.contracts.models import Approval, PaymentIntent


@dataclass(frozen=True)
class HoldState:
    held: bool
    risk_floor: Tier


class AuthoritySource(Protocol):
    """Implementations load authenticated authority on the caller's transaction."""

    def approval(self, connection: PolicyConnection, intent: PaymentIntent) -> Approval | None: ...

    def mandate(
        self, connection: PolicyConnection, intent: PaymentIntent
    ) -> MandateSnapshot | None: ...

    def hold(self, connection: PolicyConnection, intent: PaymentIntent) -> HoldState: ...
