"""Typed results of financial commands; refusals are data so their audit can be committed."""

from dataclasses import dataclass

from backend.contracts.enums import PaymentState, ReasonCode
from backend.contracts.models import PaymentIntent, PolicyDecision


@dataclass(frozen=True)
class Created:
    intent: PaymentIntent
    decision: PolicyDecision


@dataclass(frozen=True)
class Executed:
    payment_id: str
    transfer_state: PaymentState
    audit_event_id: str
    replayed: bool = False


@dataclass(frozen=True)
class Refused:
    reason_code: ReasonCode
    audit_event_id: str
    decision: PolicyDecision | None = None
