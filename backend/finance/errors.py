"""One mapping from reason codes to the uniform DomainError envelope and HTTP status."""

from dataclasses import dataclass

from fastapi.responses import JSONResponse

from backend.contracts.enums import ReasonCode as R
from backend.contracts.models import DomainError


@dataclass(frozen=True)
class ErrorRule:
    http_status: int
    status: str
    next_action: str
    message: str
    retryable: bool = False


RULES: dict[R, ErrorRule] = {
    R.FUNDING_OWNER_APPROVAL_REQUIRED: ErrorRule(
        409, "REQUIRES_APPROVAL", "WAIT_FOR_APPROVAL", "Funding owner approval is needed first."
    ),
    R.APPROVAL_EXPIRED: ErrorRule(
        409, "REQUIRES_APPROVAL", "REQUEST_NEW_APPROVAL", "The approval has expired."
    ),
    R.APPROVAL_TERMS_MISMATCH: ErrorRule(
        409, "REQUIRES_APPROVAL", "REQUEST_NEW_APPROVAL", "The payment terms changed."
    ),
    R.QUOTE_EXPIRED: ErrorRule(409, "ERROR", "REQUEST_NEW_QUOTE", "The simulated quote expired."),
    R.INSUFFICIENT_FUNDS: ErrorRule(
        409, "ERROR", "ASK_FUNDING_OWNER", "The funding account cannot cover this payment."
    ),
    R.LIMIT_EXCEEDED: ErrorRule(
        409, "DENIED", "ASK_FUNDING_OWNER", "A configured spending limit blocks this payment."
    ),
    R.SECURITY_HOLD: ErrorRule(403, "HELD", "SECURITY_REVIEW", "A security review is required."),
    R.UNKNOWN_BENEFICIARY: ErrorRule(
        403, "HELD", "VERIFY_BENEFICIARY", "The payee is not a verified recipient."
    ),
    R.BENEFICIARY_MISMATCH: ErrorRule(
        403, "HELD", "VERIFY_BENEFICIARY", "The payee does not match the verified registry."
    ),
    R.UNIVERSITY_POLICY_UNKNOWN: ErrorRule(
        409, "PENDING", "CHECK_POLICY", "The university payment policy cannot be confirmed."
    ),
    R.PROVIDER_OUTCOME_UNKNOWN: ErrorRule(
        409, "PENDING", "CHECK_STATUS", "The earlier payment outcome is still unknown."
    ),
    R.PAYMENT_ALREADY_SUBMITTED: ErrorRule(
        409, "ERROR", "CHECK_STATUS", "A payment for this request already exists."
    ),
    R.RECONCILIATION_NEEDS_INFO: ErrorRule(
        409, "PENDING", "PROVIDE_EVIDENCE", "An earlier payment needs reconciliation first."
    ),
    R.POSTING_WINDOW_ACTIVE: ErrorRule(
        409, "PENDING", "WAIT_FOR_POSTING", "The university is still within its posting window."
    ),
    R.TOPUP_NOT_PERMITTED: ErrorRule(
        409, "DENIED", "CONTACT_UNIVERSITY", "A top-up is not permitted by the synthetic policy."
    ),
    R.INVALID_SCOPE: ErrorRule(403, "DENIED", "NONE", "This action is not permitted."),
    R.IDEMPOTENCY_KEY_REUSED: ErrorRule(
        422, "ERROR", "USE_NEW_KEY", "This idempotency key belongs to a different request."
    ),
}
# A requester who does not own the funds must not learn whether the owner can afford a payment.
FUNDS_REASONS = frozenset({R.INSUFFICIENT_FUNDS, R.LIMIT_EXCEEDED})
OWNER_ONLY_FALLBACK = R.FUNDING_OWNER_APPROVAL_REQUIRED


def build_error(
    reason: R, audit_event_id: str, resource_id: str | None, *, requester_owns_funds: bool = True
) -> tuple[int, DomainError]:
    if reason in FUNDS_REASONS and not requester_owns_funds:
        reason = OWNER_ONLY_FALLBACK
        rule = ErrorRule(
            409, "PENDING", "ASK_FUNDING_OWNER", "Ask the funding owner to review this payment."
        )
    else:
        rule = RULES[reason]
    error = DomainError(
        status=rule.status,  # type: ignore[arg-type]
        reason_code=reason,
        resource_id=resource_id,
        message=rule.message,
        retryable=rule.retryable,
        next_action=rule.next_action,
        audit_event_id=audit_event_id,
    )
    return rule.http_status, error


def error_response(
    reason: R, audit_event_id: str, resource_id: str | None, *, requester_owns_funds: bool = True
) -> JSONResponse:
    status_code, error = build_error(
        reason, audit_event_id, resource_id, requester_owns_funds=requester_owns_funds
    )
    return JSONResponse(error.model_dump(mode="json"), status_code=status_code)
