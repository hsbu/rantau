"""Tuition obligation state is derived from ledger rows, never from provider status."""

from dataclasses import dataclass
from datetime import datetime

from backend.authz.policy_repository import PolicyConnection
from backend.contracts.enums import CaseState, PaymentState, TuitionState
from backend.contracts.models import TuitionObligation
from backend.finance.records import Row

OPEN_CASE_STATES = frozenset(
    {CaseState.OPEN, CaseState.EVIDENCE_REQUIRED, CaseState.READY, CaseState.SUBMITTED}
    | {CaseState.UNDER_REVIEW}
)
IGNORED_CASE_STATES = (CaseState.RESOLVED.value, CaseState.REJECTED.value)


@dataclass(frozen=True)
class ObligationSnapshot:
    obligation: TuitionObligation
    posting_deadline_at: datetime | None
    active_case_id: str | None
    latest_transfer_id: str | None
    latest_transfer_state: PaymentState | None


def derive_obligation_state(
    amount_due_minor: int,
    posted_minor: int,
    *,
    unresolved_transfer: bool = False,
    unmatched_receipt: bool = False,
    window_elapsed: bool = False,
    case_state: CaseState | None = None,
) -> TuitionState:
    if posted_minor > amount_due_minor:
        raise ValueError("Posted amount cannot exceed the amount due")
    if posted_minor == amount_due_minor:
        return TuitionState.PAID
    if case_state == CaseState.ESCALATED:
        return TuitionState.ESCALATED
    if case_state in OPEN_CASE_STATES:
        return TuitionState.RECONCILIATION_PENDING
    if case_state == CaseState.NEEDS_INFO or unmatched_receipt or window_elapsed:
        return TuitionState.EXCEPTION
    if unresolved_transfer:
        return TuitionState.AWAITING_POSTING
    return TuitionState.PARTIALLY_POSTED if posted_minor > 0 else TuitionState.UNPAID


def read_obligation(
    connection: PolicyConnection, tenant_id: str, row: Row, now: datetime
) -> ObligationSnapshot:
    alias = row["alias"]
    posted = _scalar(
        connection,
        "SELECT COALESCE(sum(posted_minor), 0) FROM university_postings "
        "WHERE tenant_id = %s AND obligation_alias = %s",
        (tenant_id, alias),
    )
    receipts = connection.execute(
        "SELECT match_status, window_deadline, post_after FROM university_receipts "
        "WHERE tenant_id = %s AND obligation_alias = %s",
        (tenant_id, alias),
    ).fetchall()
    unposted = [r for r in receipts if r["match_status"] in ("MATCHED", "UNMATCHED")]
    case = connection.execute(
        "SELECT alias, state FROM reconciliation_cases WHERE tenant_id = %s "
        "AND obligation_alias = %s AND state <> ALL(%s) ORDER BY created_at DESC LIMIT 1",
        (tenant_id, alias, list(IGNORED_CASE_STATES)),
    ).fetchone()
    transfer = connection.execute(
        "SELECT alias, state, blocks_obligation FROM transfers WHERE tenant_id = %s "
        "AND obligation_alias = %s ORDER BY created_at DESC LIMIT 1",
        (tenant_id, alias),
    ).fetchone()
    state = derive_obligation_state(
        row["amount_due_minor"],
        posted,
        unresolved_transfer=bool(transfer and transfer["blocks_obligation"]),
        unmatched_receipt=any(r["match_status"] == "UNMATCHED" for r in unposted),
        window_elapsed=any(
            r["match_status"] == "MATCHED" and r["window_deadline"] < now < r["post_after"]
            for r in unposted
        ),
        case_state=CaseState(case["state"]) if case else None,
    )
    deadlines = [r["window_deadline"] for r in unposted]
    return ObligationSnapshot(
        obligation=TuitionObligation(
            id=alias,
            student_id=row["student_id"],
            university_id=row["university_id"],
            amount_due_minor=row["amount_due_minor"],
            posted_minor=posted,
            balance_minor=row["amount_due_minor"] - posted,
            due_at=row["due_at"],
            policy_id=row["policy_alias"],
            state=state,
        ),
        posting_deadline_at=min(deadlines) if deadlines else None,
        active_case_id=case["alias"] if case else None,
        latest_transfer_id=transfer["alias"] if transfer else None,
        latest_transfer_state=PaymentState(transfer["state"]) if transfer else None,
    )


def _scalar(connection: PolicyConnection, sql: str, params: tuple[str, ...]) -> int:
    row = connection.execute(sql, params).fetchone()
    assert row is not None
    return int(next(iter(row.values())))
