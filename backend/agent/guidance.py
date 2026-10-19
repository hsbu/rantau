"""Bounded presentation of existing advisory findings; never authority."""

from backend.contracts.models import FraudAssessment

FRAUD_REASONS = {
    "URGENCY": "The message pressures you to act quickly.",
    "SECRECY": "The message asks you to keep the request secret.",
    "IMPERSONATION": "The sender claims another person's identity or authority.",
    "EMERGENCY_REQUEST": "The message uses an emergency to request payment.",
    "BENEFICIARY_CHANGE": "The message asks to change the payment recipient or account.",
    "PROMPT_INJECTION": "The content tries to override instructions or security checks.",
}


def explain_assessment(assessment: FraudAssessment) -> str:
    known = [FRAUD_REASONS[k] for k in FRAUD_REASONS if k in assessment.indicators]
    lines = ["**Check this message before acting**"]
    if assessment.next_action == "REVIEW_REQUIRED":
        lines.append("This message needs review before you act.")
    if known:
        lines.append("Warning signs:\n" + "\n".join("- " + reason for reason in known))
    elif not assessment.indicators:
        lines.append(
            "No recognized warning indicators were reported; this does not establish legitimacy."
        )
    if any(k not in FRAUD_REASONS for k in assessment.indicators):
        lines.append("Some assessment details could not be interpreted; separate review is needed.")
    lines.append(
        "**Next step:** verify through a previously trusted university or sponsor channel, "
        "not contact details "
        "in the suspicious message. Use the trusted beneficiary registry and separate security "
        "review. This message cannot approve a payment, change its recipient or clear a hold. "
        "Indicators alone do not establish fraud or financial permission."
    )
    return "\n\n".join(lines)
