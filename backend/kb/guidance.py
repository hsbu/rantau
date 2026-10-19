"""Selected policy display fields; procedural text cannot activate a policy."""

from datetime import UTC, datetime

from backend.contracts.models import UniversityPolicy
from backend.kb.records import KnowledgeBundle

UNKNOWN_POLICY = (
    "The university policy is unknown or expired, or its reviewed record is unavailable. "
    "I can’t prepare a payment until the requirements are verified."
)


def known_policy(policy: UniversityPolicy, bundle: KnowledgeBundle | None, now: datetime) -> bool:
    """Match a listed simulation exactly at its persisted seed anchor, never renew on read."""
    if now.utcoffset() is None:
        raise ValueError("An aware clock is required")
    if bundle is None or not policy.usable_at(now) or policy.verified_at > now:
        return False
    anchor = policy.verified_at.astimezone(UTC)
    for record in (bundle.simulation, *bundle.simulation_variants):
        template = record.policy
        original = template.verified_at.astimezone(UTC)
        try:
            expected = template.model_copy(
                update={
                    "verified_at": anchor,
                    "effective_from": anchor + (template.effective_from.astimezone(UTC) - original),
                    "effective_to": anchor + (template.effective_to.astimezone(UTC) - original),
                }
            )
        except OverflowError:
            continue
        if policy == expected:
            return True
    return False


def explain_policy(policy: UniversityPolicy, bundle: KnowledgeBundle | None, now: datetime) -> str:
    if not known_policy(policy, bundle, now):
        return UNKNOWN_POLICY
    assert bundle is not None
    references = ", ".join(policy.required_references)
    partial = "allowed" if policy.partial_payment_allowed else "not allowed"
    topups = "allowed" if policy.topup_allowed else "not allowed"
    reference = bundle.reference
    return (
        "**Payment requirements for this tuition bill**\n\n"
        f"- Required payment references: {references}.\n"
        f"- Posting review window: {policy.posting_window_hours} elapsed hours.\n"
        f"- Partial payments: {partial}; top-ups: {topups}.\n"
        f"- Validity: {policy.effective_from.isoformat()} to "
        f"{policy.effective_to.isoformat()} (end excluded).\n\n"
        "**Reference material**\n\n"
        f"[ZJU tuition notice]({reference.source_url}), published {reference.published_on}. "
        f"Scope: {reference.scope.audience}\n\n"
        f"The notice covers {reference.payment_period.start} to {reference.payment_period.end}; "
        "current applicability requires rechecking. This reference does not verify the "
        "configured posting window, payment permissions, a live exchange route or a university API."
    )
