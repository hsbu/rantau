"""Validated transport data; a valid shape never proves financial authority."""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.contracts.enums import (
    CURRENCY_SCALE,
    ApprovalState,
    CaseState,
    Currency,
    Decision,
    PaymentState,
    ReasonCode,
    Role,
    Tier,
    TuitionState,
)

Minor = Annotated[int, Field(strict=True, ge=0, le=9_007_199_254_740_991)]
PositiveMinor = Annotated[int, Field(strict=True, gt=0, le=9_007_199_254_740_991)]
Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ActorContext(Contract):
    actor_id: Identifier
    tenant_id: Identifier
    session_id: Identifier
    role: Role
    scopes: frozenset[str]


class Money(Contract):
    currency: Currency
    amount_minor: Minor


class FxQuote(Contract):
    id: Identifier
    provider: str
    source_country: Literal["ID"] = "ID"
    destination_country: Literal["CN"] = "CN"
    source_currency: Currency
    destination_currency: Currency
    source_principal_minor: PositiveMinor
    fee_minor: Minor
    source_total_minor: PositiveMinor
    destination_amount_minor: PositiveMinor
    rate: Annotated[str, Field(max_length=40, pattern=r"^(?:0|[1-9]\d{0,8})(?:\.\d{1,28})?$")]
    expires_at: AwareDatetime
    estimated_delivery_at: AwareDatetime
    synthetic: Literal[True] = True

    @model_validator(mode="after")
    def consistent_quote(self) -> Self:
        if self.source_total_minor != self.source_principal_minor + self.fee_minor:
            raise ValueError("Quote total must equal principal plus fee")
        try:
            rate = Decimal(self.rate)
        except InvalidOperation as exc:
            raise ValueError("Rate must be an exact positive decimal string") from exc
        if not rate.is_finite() or rate <= 0:
            raise ValueError("Rate must be an exact positive decimal string")
        source = Decimal(self.source_principal_minor).scaleb(-CURRENCY_SCALE[self.source_currency])
        converted = (source * rate).scaleb(CURRENCY_SCALE[self.destination_currency])
        if converted.quantize(Decimal(1), rounding=ROUND_HALF_UP) != self.destination_amount_minor:
            raise ValueError("Quote rate and destination amount must agree")
        return self


class TuitionObligation(Contract):
    id: Identifier
    student_id: Identifier
    university_id: Identifier
    currency: Literal[Currency.CNY] = Currency.CNY
    amount_due_minor: PositiveMinor
    posted_minor: Minor
    balance_minor: Minor
    due_at: AwareDatetime
    policy_id: Identifier
    state: TuitionState

    @model_validator(mode="after")
    def consistent_ledger(self) -> Self:
        if self.posted_minor > self.amount_due_minor:
            raise ValueError("Posted amount cannot exceed this obligation")
        if self.balance_minor != self.amount_due_minor - self.posted_minor:
            raise ValueError("Balance must equal due minus verified postings")
        if (self.state == TuitionState.PAID) != (self.balance_minor == 0):
            raise ValueError("PAID requires a fully posted obligation")
        return self


class ProviderStatusRef(Contract):
    """Provider delivery is reported separately from the university's posted balance."""

    payment_id: Identifier
    transfer_status: PaymentState


class TuitionObligationDetail(TuitionObligation):
    provider_status: ProviderStatusRef | None = None
    posting_deadline_at: AwareDatetime | None = None
    active_case_id: Identifier | None = None
    shortfall_minor: Minor = 0
    topup_permitted: bool = False


class TrustedBeneficiary(Contract):
    id: Identifier
    owner_id: Identifier
    masked_display: str
    fingerprint: str
    verified: bool


class UniversityPolicy(Contract):
    id: Identifier
    university_id: Identifier
    term_id: Identifier
    version: str
    required_references: tuple[str, ...]
    posting_window_hours: Annotated[int, Field(strict=True, gt=0)]
    partial_payment_allowed: bool
    topup_allowed: bool
    source_url: str
    verified_at: AwareDatetime
    effective_from: AwareDatetime
    effective_to: AwareDatetime
    certainty: Literal["SYNTHETIC", "UNKNOWN"]
    synthetic: Literal[True] = True

    @model_validator(mode="after")
    def ordered_validity(self) -> Self:
        if self.effective_from >= self.effective_to:
            raise ValueError("Policy validity window must be ordered")
        return self

    def usable_at(self, now: datetime) -> bool:
        return self.certainty != "UNKNOWN" and self.effective_from <= now < self.effective_to


class PaymentTerms(Contract):
    intent_id: Identifier
    intent_revision: Annotated[int, Field(strict=True, gt=0)]
    funding_owner_id: Identifier
    source_account_id: Identifier
    beneficiary_id: Identifier
    beneficiary_fingerprint: str
    purpose: Literal["TUITION", "ALLOWANCE"]
    obligation_id: Identifier | None
    source_currency: Currency
    destination_currency: Currency
    source_total_minor: PositiveMinor
    destination_amount_minor: PositiveMinor
    quote_id: Identifier
    quote_expiry: AwareDatetime
    policy_version: str
    terms_hash: str

    @model_validator(mode="after")
    def tuition_has_obligation(self) -> Self:
        if self.purpose == "TUITION" and self.obligation_id is None:
            raise ValueError("Tuition terms require an obligation")
        return self


class PaymentIntent(PaymentTerms):
    id: Identifier
    requested_by: Identifier
    tier: Tier
    state: PaymentState

    @model_validator(mode="after")
    def same_identity(self) -> Self:
        if self.id != self.intent_id:
            raise ValueError("Intent aliases must agree")
        return self


class PaymentIntentView(Contract):
    """Client-safe intent: no account identifiers, fingerprints or balances."""

    id: Identifier
    purpose: Literal["TUITION", "ALLOWANCE"]
    state: PaymentState
    tier: Tier
    obligation_id: Identifier | None
    source_currency: Currency
    destination_currency: Currency
    source_total_minor: PositiveMinor
    destination_amount_minor: PositiveMinor
    quote_id: Identifier
    quote_expiry: AwareDatetime
    terms_hash: str
    beneficiary_label: str
    funded_by_requester: bool


class Approval(PaymentTerms):
    id: Identifier
    approver_actor_id: Identifier
    expires_at: AwareDatetime
    state: ApprovalState
    consumed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def consumption_state(self) -> Self:
        if (self.state == ApprovalState.CONSUMED) != (self.consumed_at is not None):
            raise ValueError("Consumed approval requires its consumption timestamp")
        return self


class ActionIntent(Contract):
    action: Literal["CREATE_INTENT", "EXECUTE_PAYMENT", "SUBMIT_RECONCILIATION"]
    resource_id: Identifier
    terms_hash: str


class PolicyDecision(Contract):
    decision: Decision
    tier: Tier
    reason_code: ReasonCode | None
    audit_event_id: Identifier


class PaymentResult(Contract):
    payment_id: Identifier
    intent_id: Identifier
    provider_reference: Identifier
    transfer_status: PaymentState
    receipt_reference: Identifier | None
    audit_event_id: Identifier


class ReconciliationCase(Contract):
    id: Identifier
    payment_id: Identifier
    obligation_id: Identifier
    evidence_ids: tuple[Identifier, ...]
    evidence_missing: tuple[str, ...]
    state: CaseState
    audit_event_id: Identifier


class PermissionSummary(Contract):
    account_id: Identifier
    owner_id: Identifier
    permitted_purposes: tuple[Literal["TUITION", "ALLOWANCE"], ...]
    approval_required: bool
    # No balance or raw mandate/approval object is exposed to the agent.


class FraudAssessment(Contract):
    advisory: Literal[True] = True
    indicators: tuple[str, ...]
    next_action: Literal["VERIFY_WITH_TRUSTED_SOURCE", "REVIEW_REQUIRED"]


class DomainError(Contract):
    status: Literal["REQUIRES_APPROVAL", "HELD", "DENIED", "PENDING", "ERROR"]
    reason_code: ReasonCode
    resource_id: Identifier | None
    message: str
    retryable: bool
    next_action: str
    audit_event_id: Identifier


class ToolResponse[DataT](Contract):
    data: DataT | None = None
    error: DomainError | None = None

    @model_validator(mode="after")
    def exactly_one_result(self) -> Self:
        if (self.data is None) == (self.error is None):
            raise ValueError("Tool response must contain exactly one of data or error")
        return self


class ApprovalRequest(Contract):
    approval_id: Identifier
    intent_id: Identifier
    state: Literal["AWAITING_APPROVAL"] = "AWAITING_APPROVAL"


class IntentProposal(Contract):
    obligation_id: Identifier | None
    source_account_id: Identifier
    beneficiary_id: Identifier
    quote_id: Identifier
    purpose: Literal["TUITION", "ALLOWANCE"]


class ScopeDenied(Exception):
    """Resource access denied; the public response must not identify the resource."""


class ServiceUnavailable(Exception):
    """A trusted adapter is unavailable; never expose the underlying exception."""


class ContractFailure(Exception):
    """A domain adapter returned a typed error rather than usable data."""


class PolicyLookup(Contract):
    university_id: Identifier
    term_id: Identifier


class CaseSubmission(Contract):
    payment_id: Identifier
    obligation_id: Identifier
    evidence_ids: tuple[Identifier, ...]


class ExactDecimal(Contract):
    value: str

    @field_validator("value")
    @classmethod
    def exact(cls, value: str) -> str:
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("Invalid decimal") from exc
        if not parsed.is_finite():
            raise ValueError("Invalid decimal")
        return value
