"""Allowlisted durable diagnostics; assistant/user prose is never stored."""

from typing import Literal

from pydantic import Field

from backend.agent.openrouter_classifier import redact_for_model
from backend.contracts.enums import Intent
from backend.contracts.http import AgentResponse, ResourceReference, ToolEvent
from backend.contracts.models import Contract, ServiceUnavailable

SAFE_MESSAGE = (
    "Saved agent run diagnostics. Recheck current resource state before continuing; "
    "this record grants no financial authority. Original chat text is not retained."
)
TOOLS = frozenset(
    {
        "classify_intent",
        "domain_read",
        "clarify_tuition",
        "get_tuition_obligation",
        "get_university_payment_policy",
        "get_account_permissions",
        "get_fx_quotes",
        "get_trusted_beneficiary",
        "build_tuition_preview",
        "create_payment_intent",
        "revise_payment_intent",
        "request_approval",
        "get_approval_status",
        "execute_payment",
        "get_payment_status",
        "assess_fraud_risk",
        "place_security_hold",
        "create_security_case",
        "get_security_case",
        "create_reconciliation_case",
        "submit_reconciliation_case",
        "get_reconciliation_status",
        "list_student_payments",
        "select_student_payment",
        "lookup_shortfall_sources",
    }
)
MAX_RUN_BYTES = 32 * 1024


class RunRecord(Contract):
    schema_version: Literal[1] = 1
    requested_action: Intent | None
    tool_events: tuple[ToolEvent, ...] = Field(default=(), max_length=64)
    resources: tuple[ResourceReference, ...] = Field(default=(), max_length=64)

    def response(self, run_id: str) -> AgentResponse:
        return AgentResponse(
            run_id=run_id,
            message=SAFE_MESSAGE,
            requested_action=self.requested_action,
            tool_events=self.tool_events,
            resources=self.resources,
        )


def project_run(response: AgentResponse) -> RunRecord:
    if len(response.tool_events) > 64 or len(response.resources) > 64:
        raise ServiceUnavailable("Agent diagnostics exceed storage bounds")
    if any(event.tool not in TOOLS for event in response.tool_events):
        raise ServiceUnavailable("Agent diagnostics contain an unsupported tool")
    if any(redact_for_model(ref.id) != ref.id for ref in response.resources):
        raise ServiceUnavailable("Agent diagnostics contain a private reference")
    ids = {ref.id for ref in response.resources}
    try:
        record = RunRecord.model_validate(
            {
                "requested_action": response.requested_action,
                "tool_events": [
                    event.model_dump(mode="json", warnings="error")
                    | {"resource_id": event.resource_id if event.resource_id in ids else None}
                    for event in response.tool_events
                ],
                "resources": [
                    ref.model_dump(mode="json", warnings="error") for ref in response.resources
                ],
            }
        )
    except (ValueError, TypeError):
        raise ServiceUnavailable("Agent diagnostics are invalid") from None
    if len(record.model_dump_json().encode()) > MAX_RUN_BYTES:
        raise ServiceUnavailable("Agent diagnostics exceed storage bounds")
    return record
