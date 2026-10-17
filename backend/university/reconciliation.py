"""Reconciliation cases: students submit evidence; only the review service resolves them."""

import hashlib
from collections.abc import Mapping
from uuid import uuid4

from backend.authz.policy_repository import PolicyConnection
from backend.authz.storage import Database
from backend.contracts.enums import CaseState as C
from backend.contracts.enums import Decision
from backend.contracts.models import (
    ActionIntent,
    ActorContext,
    CaseSubmission,
    ReconciliationCase,
    ScopeDenied,
)
from backend.finance.audit import AuditEvent, AuditWriter
from backend.finance.authorization import GateFactory, evaluate_gate
from backend.finance.records import Row, fetch
from backend.finance.simclock import sim_now
from backend.finance.states import require_transition
from backend.university.ledger import OverpaymentError, post_receipt
from backend.university.rules import (
    REQUIRED_EVIDENCE,
    ReviewDecision,
    ReviewFacts,
    ReviewReason,
    Verdict,
    review,
)

CASE_TRANSITIONS: Mapping[C, frozenset[C]] = {
    C.OPEN: frozenset({C.EVIDENCE_REQUIRED, C.READY}),
    C.EVIDENCE_REQUIRED: frozenset({C.READY}),
    C.READY: frozenset({C.SUBMITTED}),
    C.SUBMITTED: frozenset({C.UNDER_REVIEW}),
    C.UNDER_REVIEW: frozenset({C.RESOLVED, C.REJECTED, C.NEEDS_INFO, C.ESCALATED}),
    C.NEEDS_INFO: frozenset({C.EVIDENCE_REQUIRED, C.READY}),
    C.RESOLVED: frozenset(),
    C.REJECTED: frozenset(),
    C.ESCALATED: frozenset(),
}
_VERDICT_STATE = {
    Verdict.RESOLVE: C.RESOLVED,
    Verdict.NEEDS_INFO: C.NEEDS_INFO,
    Verdict.ESCALATE: C.ESCALATED,
}


class CaseService:
    def __init__(self, database: Database, gate: GateFactory, audit: AuditWriter | None = None):
        self.database = database
        self.gate = gate
        self.audit = audit or AuditWriter()

    def create(self, actor: ActorContext, submission: CaseSubmission) -> ReconciliationCase:
        with self.database.connection() as connection:
            transfer = _own_transfer(connection, actor, submission)
            existing = _active_case(connection, actor.tenant_id, transfer["alias"])
            case = existing or _insert_case(connection, actor, transfer)
            _attach_evidence(connection, actor, case, transfer)
            return self._view(connection, actor, case["alias"], "RECONCILIATION_CASE_OPENED")

    def submit(self, actor: ActorContext, case_alias: str) -> ReconciliationCase:
        with self.database.connection() as connection:
            case = _own_case(connection, actor, case_alias, lock=True)
            transfer = fetch_transfer(connection, actor.tenant_id, case["transfer_alias"])
            _attach_evidence(connection, actor, case, transfer)
            case = _own_case(connection, actor, case_alias, lock=True)
            if C(case["state"]) == C.EVIDENCE_REQUIRED:
                return self._view(connection, actor, case_alias, "RECONCILIATION_NEEDS_EVIDENCE")
            decision = evaluate_gate(
                self.gate,
                connection,
                actor,
                ActionIntent(action="SUBMIT_RECONCILIATION", resource_id=case_alias, terms_hash=""),
            )
            if decision.decision != Decision.ALLOW:
                raise ScopeDenied("Resource unavailable")
            _move(connection, case, C.SUBMITTED)
            return self._view(connection, actor, case_alias, "RECONCILIATION_SUBMITTED")

    def get(self, actor: ActorContext, case_alias: str) -> ReconciliationCase:
        with self.database.connection() as connection:
            _own_case(connection, actor, case_alias)
            return self._view(connection, actor, case_alias, None)

    def _view(
        self, connection: PolicyConnection, actor: ActorContext, alias: str, action: str | None
    ) -> ReconciliationCase:
        case = fetch_case(connection, actor.tenant_id, alias)
        evidence = connection.execute(
            "SELECT alias FROM reconciliation_evidence WHERE tenant_id = %s AND case_alias = %s "
            "ORDER BY kind",
            (actor.tenant_id, alias),
        ).fetchall()
        audit_id = self.audit.record(
            connection,
            AuditEvent(
                tenant_id=actor.tenant_id,
                actor_id=actor.actor_id,
                action=action or "RECONCILIATION_VIEWED",
                resource_type="reconciliation_case",
                resource_id=alias,
                after_state={"state": case["state"]},
            ),
        )
        return ReconciliationCase(
            id=alias,
            payment_id=case["transfer_alias"],
            obligation_id=case["obligation_alias"],
            evidence_ids=tuple(row["alias"] for row in evidence),
            evidence_missing=tuple(case["evidence_missing"]),
            state=C(case["state"]),
            audit_event_id=audit_id,
        )


class ReviewService:
    """The simulated university. It trusts only its own records, never an agent's claims."""

    def __init__(self, database: Database, audit: AuditWriter | None = None) -> None:
        self.database = database
        self.audit = audit or AuditWriter()

    def review_submitted(self, tenant_id: str) -> list[str]:
        with self.database.connection() as connection:
            aliases = [
                row["alias"]
                for row in connection.execute(
                    "SELECT alias FROM reconciliation_cases WHERE tenant_id = %s "
                    "AND state = 'SUBMITTED' ORDER BY created_at",
                    (tenant_id,),
                ).fetchall()
            ]
        for alias in aliases:
            self.review_case(tenant_id, alias)
        return aliases

    def review_case(self, tenant_id: str, case_alias: str) -> C:
        with self.database.connection() as connection:
            peek = fetch_case(connection, tenant_id, case_alias)
            connection.execute(
                "SELECT 1 FROM tuition_obligations WHERE tenant_id = %s AND alias = %s FOR UPDATE",
                (tenant_id, peek["obligation_alias"]),
            )
            case = connection.execute(
                "SELECT * FROM reconciliation_cases WHERE tenant_id = %s AND alias = %s FOR UPDATE",
                (tenant_id, case_alias),
            ).fetchone()
            assert case is not None
            if C(case["state"]) != C.SUBMITTED:
                return C(case["state"])
            _move(connection, case, C.UNDER_REVIEW)
            case = fetch_case(connection, tenant_id, case_alias)
            decision = self._decide(connection, tenant_id, case)
            return self._conclude(connection, tenant_id, case, decision)

    def _decide(self, connection: PolicyConnection, tenant_id: str, case: Row) -> ReviewDecision:
        transfer = fetch_transfer(connection, tenant_id, case["transfer_alias"])
        receipt = connection.execute(
            "SELECT * FROM university_receipts WHERE tenant_id = %s AND transfer_alias = %s "
            "FOR UPDATE",
            (tenant_id, transfer["alias"]),
        ).fetchone()
        obligation = fetch(connection, "obligation", tenant_id, case["obligation_alias"])
        intent = fetch(connection, "intent", tenant_id, transfer["intent_alias"])
        assert obligation is not None and intent is not None
        evidence = connection.execute(
            "SELECT kind, data_digest FROM reconciliation_evidence "
            "WHERE tenant_id = %s AND case_alias = %s",
            (tenant_id, case["alias"]),
        ).fetchall()
        claimed = next((e for e in evidence if e["kind"] == "STUDENT_REFERENCE_CLAIM"), None)
        student = obligation["student_id"]
        posted = connection.execute(
            "SELECT COALESCE(sum(posted_minor), 0) AS total, "
            "bool_or(transfer_alias = %s) AS has_posting FROM university_postings "
            "WHERE tenant_id = %s AND obligation_alias = %s",
            (transfer["alias"], tenant_id, obligation["alias"]),
        ).fetchone()
        assert posted is not None
        return review(
            ReviewFacts(
                receipt=receipt,
                transfer=transfer,
                obligation=obligation,
                requester_id=intent["requested_by"],
                evidence_kinds=frozenset(e["kind"] for e in evidence),
                claimed_student=student
                if claimed and claimed["data_digest"] == _digest(student)
                else None,
                existing_posting=bool(posted["has_posting"]),
                posted_total_minor=int(posted["total"]),
            )
        )

    def _conclude(
        self, connection: PolicyConnection, tenant_id: str, case: Row, decision: ReviewDecision
    ) -> C:
        target = _VERDICT_STATE[decision.verdict]
        if decision.verdict == Verdict.RESOLVE and decision.reason != ReviewReason.ALREADY_POSTED:
            receipt = connection.execute(
                "SELECT * FROM university_receipts WHERE tenant_id = %s AND transfer_alias = %s",
                (tenant_id, case["transfer_alias"]),
            ).fetchone()
            assert receipt is not None
            try:
                post_receipt(
                    connection,
                    tenant_id,
                    receipt,
                    "RECONCILIATION",
                    sim_now(connection, tenant_id),
                    case["alias"],
                )
            except OverpaymentError:
                decision = ReviewDecision(Verdict.ESCALATE, ReviewReason.OVERPAYMENT)
                target = C.ESCALATED
        _move(connection, case, target, decision.verdict.value, decision.reason.value)
        self.audit.record(
            connection,
            AuditEvent(
                tenant_id=tenant_id,
                action="RECONCILIATION_REVIEWED",
                resource_type="reconciliation_case",
                resource_id=case["alias"],
                decision=decision.verdict.value,
                reason_code=decision.reason.value,
                after_state={"state": target.value},
            ),
        )
        return target


def fetch_case(connection: PolicyConnection, tenant_id: str, alias: str) -> Row:
    row = connection.execute(
        "SELECT * FROM reconciliation_cases WHERE tenant_id = %s AND alias = %s",
        (tenant_id, alias),
    ).fetchone()
    if row is None:
        raise ScopeDenied("Resource unavailable")
    return row


def fetch_transfer(connection: PolicyConnection, tenant_id: str, alias: str) -> Row:
    row = connection.execute(
        "SELECT t.*, i.requested_by FROM transfers t JOIN payment_intents i "
        "ON i.tenant_id = t.tenant_id AND i.alias = t.intent_alias "
        "WHERE t.tenant_id = %s AND t.alias = %s",
        (tenant_id, alias),
    ).fetchone()
    if row is None:
        raise ScopeDenied("Resource unavailable")
    return row


def _own_transfer(connection: PolicyConnection, actor: ActorContext, sub: CaseSubmission) -> Row:
    obligation = fetch(connection, "obligation", actor.tenant_id, sub.obligation_id)
    if obligation is None or obligation["student_id"] != actor.actor_id:
        raise ScopeDenied("Resource unavailable")
    transfer = fetch_transfer(connection, actor.tenant_id, sub.payment_id)
    if (
        transfer["obligation_alias"] != obligation["alias"]
        or transfer["requested_by"] != actor.actor_id
    ):
        raise ScopeDenied("Resource unavailable")
    return transfer


def _own_case(
    connection: PolicyConnection, actor: ActorContext, alias: str, *, lock: bool = False
) -> Row:
    row = connection.execute(
        "SELECT c.*, o.student_id FROM reconciliation_cases c JOIN tuition_obligations o "
        "ON o.tenant_id = c.tenant_id AND o.alias = c.obligation_alias "
        f"WHERE c.tenant_id = %s AND c.alias = %s {'FOR UPDATE OF c' if lock else ''}",
        (actor.tenant_id, alias),
    ).fetchone()
    if row is None or row["student_id"] != actor.actor_id:
        raise ScopeDenied("Resource unavailable")
    return row


def _active_case(connection: PolicyConnection, tenant_id: str, transfer_alias: str) -> Row | None:
    return connection.execute(
        "SELECT * FROM reconciliation_cases WHERE tenant_id = %s AND transfer_alias = %s "
        "AND state NOT IN ('RESOLVED', 'REJECTED', 'ESCALATED')",
        (tenant_id, transfer_alias),
    ).fetchone()


def _insert_case(connection: PolicyConnection, actor: ActorContext, transfer: Row) -> Row:
    row = connection.execute(
        "INSERT INTO reconciliation_cases (tenant_id, alias, transfer_alias, obligation_alias, "
        "state, submitted_by) VALUES (%s, %s, %s, %s, 'OPEN', %s) RETURNING *",
        (
            actor.tenant_id,
            f"case_{uuid4().hex[:12]}",
            transfer["alias"],
            transfer["obligation_alias"],
            actor.actor_id,
        ),
    ).fetchone()
    assert row is not None
    return row


def _attach_evidence(
    connection: PolicyConnection, actor: ActorContext, case: Row, transfer: Row
) -> None:
    """Collect evidence from backend records and the authenticated identity, never from chat."""
    if C(case["state"]) in (C.SUBMITTED, C.UNDER_REVIEW, C.RESOLVED, C.ESCALATED, C.REJECTED):
        return
    delivered = transfer["delivered_destination_minor"]
    available = {
        "RECEIPT": ("SYSTEM_VERIFIED", transfer["receipt_reference"]),
        "PROVIDER_REFERENCE": ("SYSTEM_VERIFIED", transfer["provider_reference"]),
        "AMOUNT": ("SYSTEM_VERIFIED", None if delivered is None else str(delivered)),
        "STUDENT_REFERENCE_CLAIM": ("USER_SUPPLIED", actor.actor_id),
    }
    for kind, (source, value) in available.items():
        if value is None:
            continue
        connection.execute(
            "INSERT INTO reconciliation_evidence (tenant_id, alias, case_alias, kind, source, "
            "data_digest) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (tenant_id, case_alias, kind) "
            "DO UPDATE SET data_digest = EXCLUDED.data_digest",
            (
                actor.tenant_id,
                f"evidence_{uuid4().hex[:12]}",
                case["alias"],
                kind,
                source,
                _digest(value),
            ),
        )
    present = {
        row["kind"]
        for row in connection.execute(
            "SELECT kind FROM reconciliation_evidence WHERE tenant_id = %s AND case_alias = %s",
            (actor.tenant_id, case["alias"]),
        ).fetchall()
    }
    missing = sorted(REQUIRED_EVIDENCE - present)
    connection.execute(
        "UPDATE reconciliation_cases SET evidence_missing = %s WHERE tenant_id = %s AND alias = %s",
        (missing, actor.tenant_id, case["alias"]),
    )
    target = C.EVIDENCE_REQUIRED if missing else C.READY
    if C(case["state"]) != target:
        refreshed = fetch_case(connection, actor.tenant_id, case["alias"])
        _move(connection, refreshed, target)


def _move(
    connection: PolicyConnection,
    case: Row,
    target: C,
    decision: str | None = None,
    reason: str | None = None,
) -> None:
    require_transition(CASE_TRANSITIONS, C(case["state"]), target)
    updated = connection.execute(
        "UPDATE reconciliation_cases SET state = %s, version = version + 1, "
        "reviewer_decision = COALESCE(%s, reviewer_decision), "
        "reviewer_reason = COALESCE(%s, reviewer_reason), updated_at = clock_timestamp() "
        "WHERE tenant_id = %s AND alias = %s AND version = %s",
        (target.value, decision, reason, case["tenant_id"], case["alias"], case["version"]),
    )
    if updated.rowcount != 1:
        raise ScopeDenied("Resource unavailable")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
