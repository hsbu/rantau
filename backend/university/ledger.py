"""University ledger: internal, idempotent postings (never reachable from the agent)."""

from datetime import datetime
from uuid import uuid4

from backend.authz.policy_repository import PolicyConnection
from backend.finance.audit import AuditEvent, AuditWriter
from backend.finance.records import Row
from backend.finance.simclock import sim_now


class OverpaymentError(Exception):
    """A posting would exceed the amount due; it must be escalated, not posted."""


def post_receipt(
    connection: PolicyConnection,
    tenant_id: str,
    receipt: Row,
    kind: str,
    now: datetime,
    case_alias: str | None = None,
) -> bool:
    """Post a receipt once per transfer. Returns False if it was already posted."""
    obligation = connection.execute(
        "SELECT university_id, amount_due_minor FROM tuition_obligations "
        "WHERE tenant_id = %s AND alias = %s",
        (tenant_id, receipt["obligation_alias"]),
    ).fetchone()
    assert obligation is not None
    posted = connection.execute(
        "SELECT COALESCE(sum(posted_minor), 0) AS total FROM university_postings "
        "WHERE tenant_id = %s AND obligation_alias = %s",
        (tenant_id, receipt["obligation_alias"]),
    ).fetchone()
    assert posted is not None
    if posted["total"] + receipt["received_minor"] > obligation["amount_due_minor"]:
        raise OverpaymentError()
    inserted = connection.execute(
        "INSERT INTO university_postings (tenant_id, alias, institution_id, obligation_alias, "
        "transfer_alias, kind, posted_minor, posted_at) "
        "VALUES (%s, 'posting_' || substr(md5(random()::text), 1, 12), %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (tenant_id, institution_id, transfer_alias) DO NOTHING RETURNING id",
        (
            tenant_id,
            obligation["university_id"],
            receipt["obligation_alias"],
            receipt["transfer_alias"],
            kind,
            receipt["received_minor"],
            now,
        ),
    ).fetchone()
    if inserted is None:
        return False
    status = "RECONCILED" if case_alias else "POSTED"
    connection.execute(
        "UPDATE university_receipts SET match_status = %s WHERE tenant_id = %s AND alias = %s",
        (status, tenant_id, receipt["alias"]),
    )
    connection.execute(
        "UPDATE transfers SET blocks_obligation = false WHERE tenant_id = %s AND alias = %s",
        (tenant_id, receipt["transfer_alias"]),
    )
    return True


def settle_due(
    connection: PolicyConnection, tenant_id: str, obligation_alias: str | None = None
) -> int:
    """Post matched receipts whose simulated posting time has arrived; idempotent."""
    now = sim_now(connection, tenant_id)
    obligations = connection.execute(
        "SELECT alias FROM tuition_obligations WHERE tenant_id = %s "
        "AND (%s::text IS NULL OR alias = %s) ORDER BY alias FOR UPDATE",
        (tenant_id, obligation_alias, obligation_alias),
    ).fetchall()
    posted = 0
    for obligation in obligations:
        receipts = connection.execute(
            "SELECT * FROM university_receipts WHERE tenant_id = %s AND obligation_alias = %s "
            "AND match_status = 'MATCHED' AND post_after <= %s FOR UPDATE",
            (tenant_id, obligation["alias"], now),
        ).fetchall()
        for receipt in receipts:
            try:
                posted += post_receipt(connection, tenant_id, receipt, "PAYMENT", now)
            except OverpaymentError:
                _escalate_overpayment(connection, tenant_id, receipt)
    return posted


def _escalate_overpayment(connection: PolicyConnection, tenant_id: str, receipt: Row) -> None:
    """Never post beyond the amount due; hand the receipt to a human-reviewed escalated case."""
    existing = connection.execute(
        "SELECT 1 FROM reconciliation_cases WHERE tenant_id = %s AND transfer_alias = %s "
        "AND state = 'ESCALATED'",
        (tenant_id, receipt["transfer_alias"]),
    ).fetchone()
    if existing is not None:
        return
    alias = f"case_{uuid4().hex[:12]}"
    connection.execute(
        "INSERT INTO reconciliation_cases (tenant_id, alias, transfer_alias, obligation_alias, "
        "state, submitted_by, reviewer_decision, reviewer_reason) "
        "VALUES (%s, %s, %s, %s, 'ESCALATED', 'university_system', 'ESCALATE', 'OVERPAYMENT')",
        (tenant_id, alias, receipt["transfer_alias"], receipt["obligation_alias"]),
    )
    AuditWriter().record(
        connection,
        AuditEvent(
            tenant_id=tenant_id,
            action="RECONCILIATION_ESCALATED",
            resource_type="reconciliation_case",
            resource_id=alias,
            decision="ESCALATE",
            reason_code="OVERPAYMENT",
            after_state={"state": "ESCALATED"},
        ),
    )
