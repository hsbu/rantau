"""Selected policy display fields; procedural text cannot activate a policy."""

from datetime import datetime

from backend.contracts.models import UniversityPolicy
from backend.kb.records import KnowledgeBundle

UNKNOWN_POLICY = (
    "University policy is unknown or expired, or its reviewed simulation record is unavailable. "
    "Verify it before planning a payment."
)


def known_policy(policy: UniversityPolicy, bundle: KnowledgeBundle | None, now: datetime) -> bool:
    if now.utcoffset() is None:
        raise ValueError("An aware clock is required")
    return bundle is not None and policy == bundle.simulation.policy and policy.usable_at(now)


def explain_policy(
    policy: UniversityPolicy, bundle: KnowledgeBundle | None, now: datetime
) -> str:
    if not known_policy(policy, bundle, now):
        return UNKNOWN_POLICY
    assert bundle is not None
    references = ", ".join(policy.required_references)
    partial = "allowed" if policy.partial_payment_allowed else "not allowed"
    topups = "allowed" if policy.topup_allowed else "not allowed"
    reference = bundle.reference
    return (
        f"Fictional university policy {policy.version} (simulation only). "
        f"Required reference fields: {references}. "
        f"Synthetic posting window: {policy.posting_window_hours} elapsed hours. "
        f"Partial payments: {partial}; top-ups: {topups}. "
        f"Validity: {policy.effective_from.isoformat()} to {policy.effective_to.isoformat()} "
        "(end excluded). These are authored demo rules, not official university terms.\n"
        f"Procedural context: [ZJU tuition notice]({reference.source_url}), "
        f"published {reference.published_on}, reviewed {reference.reviewed_on}, "
        f"Rantau record revision {reference.revision} (reviewed draft). "
        f"Scope: {reference.scope.audience} "
        f"The notice's payment period is {reference.payment_period.start} to "
        f"{reference.payment_period.end}; current applicability requires rechecking. "
        "This citation does not establish the fictional posting window or payment permissions. "
        "It does not establish a live IDR-to-CNY route or university API."
    )
