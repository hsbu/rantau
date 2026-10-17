import pytest

from backend.contracts.enums import TuitionState
from backend.university.obligations import derive_obligation_state

DUE = 2_000_000


@pytest.mark.parametrize(
    ("posted", "unresolved", "expected"),
    [
        (0, False, TuitionState.UNPAID),
        (DUE, False, TuitionState.PAID),
        (DUE, True, TuitionState.PAID),
        (500_000, False, TuitionState.PARTIALLY_POSTED),
        (0, True, TuitionState.AWAITING_POSTING),
        (500_000, True, TuitionState.AWAITING_POSTING),
    ],
)
def test_state_comes_from_ledger_rows_and_unresolved_transfers(posted, unresolved, expected):
    assert derive_obligation_state(DUE, posted, unresolved_transfer=unresolved) == expected


def test_posting_beyond_the_amount_due_is_a_data_error():
    with pytest.raises(ValueError):
        derive_obligation_state(DUE, DUE + 1, unresolved_transfer=False)
