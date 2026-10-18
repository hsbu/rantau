"""The only definition of legal payment state changes; every writer goes through it."""

from collections.abc import Mapping
from enum import StrEnum

from backend.contracts.enums import PaymentState as S

INTENT_TRANSITIONS: Mapping[S, frozenset[S]] = {
    S.DRAFT: frozenset(
        {S.AWAITING_APPROVAL, S.AUTHORIZED, S.PROCESSING, S.ON_HOLD, S.CANCELLED, S.EXPIRED}
    ),
    S.AWAITING_APPROVAL: frozenset({S.AUTHORIZED, S.REJECTED, S.EXPIRED, S.ON_HOLD, S.CANCELLED}),
    S.AUTHORIZED: frozenset({S.PROCESSING, S.ON_HOLD, S.EXPIRED, S.CANCELLED}),
    # Only a trusted hold-clearing flow owned by Dev B may leave ON_HOLD for approval.
    S.ON_HOLD: frozenset({S.AWAITING_APPROVAL, S.CANCELLED}),
    S.PROCESSING: frozenset({S.DELIVERED, S.FAILED, S.OUTCOME_UNKNOWN}),
    S.OUTCOME_UNKNOWN: frozenset({S.DELIVERED, S.FAILED}),
    S.DELIVERED: frozenset(),
    S.FAILED: frozenset(),
    S.REJECTED: frozenset(),
    S.EXPIRED: frozenset(),
    S.CANCELLED: frozenset(),
}

TRANSFER_TRANSITIONS: Mapping[S, frozenset[S]] = {
    S.PROCESSING: frozenset({S.DELIVERED, S.FAILED, S.OUTCOME_UNKNOWN}),
    S.OUTCOME_UNKNOWN: frozenset({S.DELIVERED, S.FAILED}),
    S.DELIVERED: frozenset(),
    S.FAILED: frozenset(),
}

CANCELLABLE = frozenset(
    state for state, exits in INTENT_TRANSITIONS.items() if S.CANCELLED in exits
)


class InvalidTransition(Exception):
    """A state change outside the documented tables; never retried blindly."""


def require_transition[State: StrEnum](
    table: Mapping[State, frozenset[State]], current: State, target: State
) -> None:
    if target not in table.get(current, frozenset()):
        raise InvalidTransition(f"{current.value} -> {target.value}")
