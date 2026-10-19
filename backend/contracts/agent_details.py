"""Read-only Chat presentation; identifiers and authority payloads stay server-side."""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from backend.contracts.enums import ApprovalState, CaseState, PaymentState, TuitionState
from backend.contracts.models import Contract, FxQuote, Identifier, Minor, PositiveMinor

Label = Annotated[str, Field(min_length=1, max_length=120)]


class AgentTuitionDetail(Contract):
    amount_due_minor: PositiveMinor
    posted_minor: Minor
    balance_minor: Minor
    due_at: AwareDatetime
    state: TuitionState
    posting_deadline_at: AwareDatetime | None = None
    shortfall_minor: Minor = 0
    topup_permitted: bool = False

    @model_validator(mode="after")
    def consistent_posting(self) -> Self:
        if self.posted_minor + self.balance_minor != self.amount_due_minor:
            raise ValueError("Inconsistent tuition amounts")
        if (self.state == TuitionState.PAID) != (self.balance_minor == 0):
            raise ValueError("Paid requires fully posted tuition")
        return self


class AgentQuoteDetail(Contract):
    provider: Label
    source_currency: Literal["IDR"]
    destination_currency: Literal["CNY"]
    source_principal_minor: PositiveMinor
    fee_minor: Minor
    source_total_minor: PositiveMinor
    destination_amount_minor: PositiveMinor
    rate: Annotated[str, Field(max_length=40)]
    expires_at: AwareDatetime
    estimated_delivery_at: AwareDatetime

    @model_validator(mode="after")
    def consistent_quote(self) -> Self:
        FxQuote(id="quote_projection", **self.model_dump())
        return self


class AgentApprovalDetail(Contract):
    state: ApprovalState
    expires_at: AwareDatetime
    owner: Literal["SELF", "OTHER"]


class AgentPaymentDetail(Contract):
    transfer_status: PaymentState
    linked_posting: bool


class AgentRecoveryDetail(Contract):
    state: CaseState
    evidence_missing: Annotated[tuple[Label, ...], Field(max_length=10)]


class AgentActionSummary(Contract):
    obligation: AgentTuitionDetail
    quote: AgentQuoteDetail | None = None
    approval: AgentApprovalDetail | None = None
    payment: AgentPaymentDetail | None = None
    case: AgentRecoveryDetail | None = None
    intent_state: PaymentState | None = None
    beneficiary: Label
    funding: Label


class AgentDetailSnapshot(Contract):
    run_id: Identifier
    revision: Annotated[int, Field(strict=True, gt=0)]
    checked_at: AwareDatetime
    simulation_at: AwareDatetime
    summary: AgentActionSummary | None = None
