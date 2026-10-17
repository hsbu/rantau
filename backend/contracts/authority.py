"""B-03 owner-review transport; never expose stored account/approval payloads."""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from backend.contracts.enums import ApprovalState, Currency
from backend.contracts.models import Contract, Identifier, Minor, PositiveMinor

Label = Annotated[str, Field(min_length=1, max_length=120)]


class ReviewDisplay(Contract):
    source_label: Label
    beneficiary_label: Label
    source_principal_minor: Minor
    fee_minor: Minor


class ApprovalView(ReviewDisplay):
    approval_id: Identifier
    intent_id: Identifier
    intent_revision: Annotated[int, Field(strict=True, gt=0)]
    terms_hash: str
    state: ApprovalState
    expires_at: AwareDatetime
    purpose: Literal["TUITION", "ALLOWANCE"]
    source_currency: Currency
    destination_currency: Currency
    source_total_minor: PositiveMinor
    destination_amount_minor: PositiveMinor
    simulated: Literal[True] = True


class MandateRequest(Contract):
    source_account_id: Identifier
    delegate_id: Identifier
    beneficiary_id: Identifier
    currency: Currency
    per_transfer_limit_minor: Minor
    daily_limit_minor: Minor
    monthly_limit_minor: Minor
    starts_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if self.starts_at >= self.expires_at:
            raise ValueError("Mandate validity must be ordered")
        if not self.per_transfer_limit_minor <= self.daily_limit_minor <= self.monthly_limit_minor:
            raise ValueError("Mandate limits must be ordered")
        return self


class MandateView(Contract):
    id: Identifier
    revision: Annotated[int, Field(strict=True, gt=0)]
    source_label: Label
    beneficiary_label: Label
    currency: Currency
    per_transfer_limit_minor: Minor
    daily_limit_minor: Minor
    monthly_limit_minor: Minor
    starts_at: AwareDatetime
    expires_at: AwareDatetime
    timezone: str
    revoked: bool
    simulated: Literal[True] = True
