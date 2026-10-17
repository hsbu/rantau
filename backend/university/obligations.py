"""Tuition obligation state is derived from ledger rows, never from provider status."""

from backend.contracts.enums import TuitionState


def derive_obligation_state(
    amount_due_minor: int, posted_minor: int, *, unresolved_transfer: bool
) -> TuitionState:
    if posted_minor > amount_due_minor:
        raise ValueError("Posted amount cannot exceed the amount due")
    if posted_minor == amount_due_minor:
        return TuitionState.PAID
    if unresolved_transfer:
        return TuitionState.AWAITING_POSTING
    if posted_minor > 0:
        return TuitionState.PARTIALLY_POSTED
    return TuitionState.UNPAID
