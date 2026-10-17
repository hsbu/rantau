"""Approved public security-case projection; reporter and evidence stay internal."""

from typing import Literal

from pydantic import AwareDatetime

from backend.contracts.models import Contract, Identifier


class SecurityCaseView(Contract):
    case_id: Identifier
    resource_id: Identifier
    state: Literal["OPEN", "UNDER_REVIEW", "RESOLVED", "ESCALATED"]
    reason: Literal[
        "UNKNOWN_BENEFICIARY", "BENEFICIARY_MISMATCH", "BENEFICIARY_CHANGE_REQUESTED",
        "PROMPT_INJECTION", "SCAM_INDICATOR", "POLICY_REVIEW",
    ]
    created_at: AwareDatetime
    updated_at: AwareDatetime
    audit_event_id: Identifier
