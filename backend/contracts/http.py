"""v1 HTTP contracts and endpoint catalogue, independent of runtime wiring."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from backend.contracts.enums import Intent, PaymentState, Tier
from backend.contracts.models import (
    Contract,
    Identifier,
    IntentProposal,
    PaymentTerms,
    ReconciliationCase,
)


class AgentMessage(Contract):
    message: Annotated[str, Field(min_length=1, max_length=4000)]
    conversation_id: Identifier | None = None

    @model_validator(mode="after")
    def nonblank(self) -> "AgentMessage":
        if not self.message.strip():
            raise ValueError("Message must not be blank")
        return self


class ToolEvent(Contract):
    tool: str
    status: Literal["OK", "PENDING", "UNAVAILABLE", "DENIED"]
    resource_id: Identifier | None = None


class ResourceReference(Contract):
    kind: Literal["obligation", "payment", "case", "policy"]
    id: Identifier


class AgentResponse(Contract):
    run_id: Identifier
    message: str
    requested_action: Intent | None
    tool_events: tuple[ToolEvent, ...] = ()
    resources: tuple[ResourceReference, ...] = ()


class IntentCreated(Contract):
    id: Identifier
    terms_hash: str
    tier: Tier
    state: PaymentState
    approval_required: bool
    quote_expires_at: AwareDatetime


class ExecutionResult(Contract):
    payment_id: Identifier
    transfer_status: PaymentState
    audit_event_id: Identifier


class SponsorDecisionRequest(Contract):
    decision: Literal["APPROVED", "REJECTED"]
    terms_hash: str


class SponsorDecisionResult(Contract):
    approval_id: Identifier
    decision: Literal["APPROVED", "REJECTED"]
    intent_id: Identifier
    current_terms_hash: str
    recorded_at: AwareDatetime


class CaseCreated(Contract):
    case_id: Identifier
    status: str
    evidence_missing: tuple[str, ...]


class ContractCatalogue(Contract):
    """Expose schemas in exported OpenAPI without adding executable domain routes."""

    terms: PaymentTerms
    intent_request: IntentProposal
    intent_response: IntentCreated
    execution: ExecutionResult
    decision_request: SponsorDecisionRequest
    decision: SponsorDecisionResult
    case: ReconciliationCase
    case_created: CaseCreated


# These are a coordination catalogue, NOT an implementation of B/C HTTP services.
HTTP_ENDPOINTS = (
    ("POST", "/api/v1/agent/messages"),
    ("GET", "/api/v1/agent/runs/{run_id}"),
    ("GET", "/api/v1/tuition/obligations"),
    ("GET", "/api/v1/tuition/obligations/{id}"),
    ("GET", "/api/v1/quotes"),
    ("POST", "/api/v1/payment-intents"),
    ("GET", "/api/v1/payment-intents/{id}"),
    ("POST", "/api/v1/payment-intents/{id}/approval-requests"),
    ("GET", "/api/v1/sponsor/approvals"),
    ("POST", "/api/v1/sponsor/approvals/{id}/decision"),
    ("GET", "/api/v1/student/approvals"),
    ("POST", "/api/v1/student/approvals/{id}/decision"),
    ("GET", "/api/v1/sponsor/mandates"),
    ("POST", "/api/v1/sponsor/mandates"),
    ("PUT", "/api/v1/sponsor/mandates/{id}"),
    ("DELETE", "/api/v1/sponsor/mandates/{id}"),
    ("POST", "/api/v1/payment-intents/{id}/execute"),
    ("POST", "/api/v1/payment-intents/{id}/cancel"),
    ("GET", "/api/v1/transfers/{id}"),
    ("GET", "/api/v1/reconciliations/{id}"),
    ("POST", "/api/v1/reconciliations"),
    ("POST", "/api/v1/reconciliations/{id}/submit"),
    ("GET", "/api/v1/security-cases/{id}"),
    ("GET", "/api/v1/audit"),
    ("GET", "/api/v1/kb/universities/{id}/payment-policy"),
    ("POST", "/api/v1/demo/reset"),
    ("GET", "/api/v1/demo/scenarios"),
    ("POST", "/api/v1/auth/login"),
    ("GET", "/api/v1/auth/session"),
    ("POST", "/api/v1/auth/logout"),
    ("PUT", "/api/v1/student/sharing-consents/{sponsor_id}"),
    ("DELETE", "/api/v1/student/sharing-consents/{sponsor_id}"),
)
