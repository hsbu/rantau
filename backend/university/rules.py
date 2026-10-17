"""Pure university review rule: ACCEPT_IF_RECEIPT_PROVIDER_REFERENCE_AMOUNT_AND_STUDENT_MATCH."""

from dataclasses import dataclass
from enum import StrEnum

from backend.finance.records import Row

REQUIRED_EVIDENCE = frozenset(
    {"RECEIPT", "PROVIDER_REFERENCE", "AMOUNT", "STUDENT_REFERENCE_CLAIM"}
)


class Verdict(StrEnum):
    RESOLVE = "RESOLVE"
    NEEDS_INFO = "NEEDS_INFO"
    ESCALATE = "ESCALATE"


class ReviewReason(StrEnum):
    ALREADY_POSTED = "ALREADY_POSTED"
    VERIFIED_MATCH = "VERIFIED_MATCH"
    NO_RECEIPT = "NO_RECEIPT"
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
    REFERENCE_CONFLICT = "REFERENCE_CONFLICT"
    AMOUNT_CONFLICT = "AMOUNT_CONFLICT"
    STUDENT_CONFLICT = "STUDENT_CONFLICT"
    OVERPAYMENT = "OVERPAYMENT"


@dataclass(frozen=True)
class ReviewDecision:
    verdict: Verdict
    reason: ReviewReason


@dataclass(frozen=True)
class ReviewFacts:
    receipt: Row | None
    transfer: Row
    obligation: Row
    requester_id: str
    evidence_kinds: frozenset[str]
    claimed_student: str | None
    existing_posting: bool
    posted_total_minor: int


def review(facts: ReviewFacts) -> ReviewDecision:
    receipt = facts.receipt
    if facts.existing_posting:
        return ReviewDecision(Verdict.RESOLVE, ReviewReason.ALREADY_POSTED)
    if receipt is None:
        return ReviewDecision(Verdict.NEEDS_INFO, ReviewReason.NO_RECEIPT)
    if not REQUIRED_EVIDENCE <= facts.evidence_kinds:
        return ReviewDecision(Verdict.NEEDS_INFO, ReviewReason.EVIDENCE_INCOMPLETE)
    if (
        receipt["provider_reference"] != facts.transfer["provider_reference"]
        or receipt["transfer_alias"] != facts.transfer["alias"]
    ):
        return ReviewDecision(Verdict.ESCALATE, ReviewReason.REFERENCE_CONFLICT)
    if receipt["received_minor"] != facts.transfer["delivered_destination_minor"]:
        return ReviewDecision(Verdict.ESCALATE, ReviewReason.AMOUNT_CONFLICT)
    student = facts.obligation["student_id"]
    if facts.claimed_student != student or facts.requester_id != student:
        return ReviewDecision(Verdict.ESCALATE, ReviewReason.STUDENT_CONFLICT)
    if facts.posted_total_minor + receipt["received_minor"] > facts.obligation["amount_due_minor"]:
        return ReviewDecision(Verdict.ESCALATE, ReviewReason.OVERPAYMENT)
    return ReviewDecision(Verdict.RESOLVE, ReviewReason.VERIFIED_MATCH)
