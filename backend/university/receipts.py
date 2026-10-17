"""What the university receives: match payer references to students, queue unmatched funds."""

from datetime import timedelta
from uuid import uuid4

from backend.authz.policy_repository import PolicyConnection
from backend.contracts.models import UniversityPolicy
from backend.finance.provider import ProviderEvidence
from backend.finance.records import Row, fetch
from backend.finance.simclock import sim_now

POSTING_DELAY = timedelta(hours=24)


class UniversityReceipts:
    """Implements finance.transfers.DeliveryListener inside the delivery transaction."""

    def on_delivered(
        self,
        connection: PolicyConnection,
        tenant_id: str,
        transfer: Row,
        evidence: ProviderEvidence,
    ) -> None:
        obligation = fetch(connection, "obligation", tenant_id, transfer["obligation_alias"])
        assert obligation is not None and evidence.delivered_destination_minor is not None
        window = _posting_window(connection, tenant_id, obligation["policy_alias"])
        now = sim_now(connection, tenant_id)
        student = obligation["student_id"]
        reference = evidence.payer_reference
        matched = reference is not None and student in reference
        connection.execute(
            "INSERT INTO university_receipts (tenant_id, alias, provider_reference, "
            "transfer_alias, obligation_alias, received_minor, payer_reference_text, "
            "match_status, matched_student_id, post_after, window_deadline) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                tenant_id,
                f"receipt_{uuid4().hex[:12]}",
                transfer["provider_reference"],
                transfer["alias"],
                transfer["obligation_alias"],
                evidence.delivered_destination_minor,
                reference,
                "MATCHED" if matched else "UNMATCHED",
                student if matched else None,
                now + POSTING_DELAY,
                now + window,
            ),
        )


def _posting_window(connection: PolicyConnection, tenant_id: str, policy_alias: str) -> timedelta:
    row = connection.execute(
        "SELECT policy FROM university_policies WHERE tenant_id = %s AND alias = %s",
        (tenant_id, policy_alias),
    ).fetchone()
    assert row is not None
    return timedelta(hours=UniversityPolicy.model_validate(row["policy"]).posting_window_hours)
