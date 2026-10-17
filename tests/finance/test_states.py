import pytest

from backend.contracts.enums import PaymentState
from backend.finance.states import (
    CANCELLABLE,
    INTENT_TRANSITIONS,
    TRANSFER_TRANSITIONS,
    InvalidTransition,
    require_transition,
)

TERMINAL = {
    PaymentState.DELIVERED,
    PaymentState.FAILED,
    PaymentState.REJECTED,
    PaymentState.EXPIRED,
    PaymentState.CANCELLED,
}


def test_every_payment_state_has_an_explicit_entry():
    assert set(INTENT_TRANSITIONS) == set(PaymentState)


@pytest.mark.parametrize("state", sorted(TERMINAL))
def test_terminal_states_have_no_exit(state):
    assert INTENT_TRANSITIONS[state] == frozenset()


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (PaymentState.DRAFT, PaymentState.AWAITING_APPROVAL),
        (PaymentState.AWAITING_APPROVAL, PaymentState.AUTHORIZED),
        (PaymentState.AUTHORIZED, PaymentState.PROCESSING),
        (PaymentState.PROCESSING, PaymentState.OUTCOME_UNKNOWN),
        (PaymentState.OUTCOME_UNKNOWN, PaymentState.DELIVERED),
        (PaymentState.OUTCOME_UNKNOWN, PaymentState.FAILED),
    ],
)
def test_documented_transitions_are_allowed(current, target):
    require_transition(INTENT_TRANSITIONS, current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (PaymentState.PROCESSING, PaymentState.CANCELLED),
        (PaymentState.DELIVERED, PaymentState.PROCESSING),
        (PaymentState.FAILED, PaymentState.AUTHORIZED),
        (PaymentState.AWAITING_APPROVAL, PaymentState.PROCESSING),
        (PaymentState.ON_HOLD, PaymentState.AUTHORIZED),
    ],
)
def test_undocumented_transitions_are_rejected(current, target):
    with pytest.raises(InvalidTransition):
        require_transition(INTENT_TRANSITIONS, current, target)


def test_cancel_is_only_possible_before_processing():
    assert PaymentState.PROCESSING not in CANCELLABLE
    assert PaymentState.OUTCOME_UNKNOWN not in CANCELLABLE
    for state in CANCELLABLE:
        require_transition(INTENT_TRANSITIONS, state, PaymentState.CANCELLED)


def test_transfer_failure_is_reachable_from_unknown_only_through_the_table():
    require_transition(TRANSFER_TRANSITIONS, PaymentState.OUTCOME_UNKNOWN, PaymentState.FAILED)
    with pytest.raises(InvalidTransition):
        require_transition(TRANSFER_TRANSITIONS, PaymentState.DELIVERED, PaymentState.FAILED)
