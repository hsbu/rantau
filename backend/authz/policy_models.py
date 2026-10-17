"""Trusted backend-only financial snapshots; validation is not proof of authority.

Dev C's repository must load complete, tenant-scoped facts under the caller's
transaction locks. These models must never be bound to request/model input.
"""

from datetime import date
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, field_validator, model_validator

from backend.contracts.enums import Currency, Tier
from backend.contracts.models import (
    Approval,
    Contract,
    FxQuote,
    Identifier,
    Minor,
    PaymentIntent,
    PositiveMinor,
    TrustedBeneficiary,
    TuitionObligation,
    UniversityPolicy,
)


class AccountSnapshot(Contract):
    id: Identifier
    tenant_id: Identifier
    owner_id: Identifier
    active: bool
    owner_active: bool
    currency: Currency
    timezone: str
    available_minor: Minor
    per_transfer_limit_minor: Minor
    daily_limit_minor: Minor
    monthly_limit_minor: Minor

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("An IANA account timezone is required") from exc
        return value


class PolicyRules(Contract):
    version: Identifier
    effective_from: AwareDatetime
    effective_to: AwareDatetime
    routine_threshold_minor: Minor
    purposes: frozenset[Literal["TUITION", "ALLOWANCE"]]
    currency_pairs: frozenset[tuple[Currency, Currency]]

    @model_validator(mode="after")
    def ordered_validity(self) -> Self:
        if self.effective_from >= self.effective_to:
            raise ValueError("Policy validity must be ordered")
        return self


class SpendingEntry(Contract):
    """One latest completed/reserved charge per intent for this payer account.

    Include all history relevant to the current day/month and every outstanding
    reservation, including the candidate's. `at` is its accounting timestamp in
    UTC (aware offsets are equivalent). Never include reversed/released charges.
    """

    intent_id: Identifier
    account_id: Identifier
    currency: Currency
    amount_minor: PositiveMinor
    state: Literal["COMPLETED", "RESERVED"]
    at: AwareDatetime


class MandateSnapshot(Contract):
    """Current authenticated owner mandate, loaded from trusted storage only."""

    id: Identifier
    owner_id: Identifier
    delegate_id: Identifier
    account_id: Identifier
    beneficiary_id: Identifier
    beneficiary_fingerprint: str
    currency: Currency
    purpose: Literal["TUITION", "ALLOWANCE"]
    per_transfer_limit_minor: Minor
    daily_limit_minor: Minor
    monthly_limit_minor: Minor
    starts_at: AwareDatetime
    expires_at: AwareDatetime
    revoked: bool

    @model_validator(mode="after")
    def ordered_validity(self) -> Self:
        if self.starts_at >= self.expires_at:
            raise ValueError("Mandate validity must be ordered")
        return self


class PaymentSnapshot(Contract):
    tenant_id: Identifier
    intent: PaymentIntent
    account: AccountSnapshot
    # Derived from stored funding relationships, not sharing consent alone.
    authorized_requesters: frozenset[Identifier]
    beneficiary: TrustedBeneficiary
    recipient_owner_id: Identifier
    quote: FxQuote
    rules: PolicyRules
    spending: tuple[SpendingEntry, ...]
    mandate: MandateSnapshot | None
    # B-03 supplies only approvals recorded by its authenticated owner flow.
    approval: Approval | None
    held: bool
    risk_floor: Tier
    obligation: TuitionObligation | None
    university_policy: UniversityPolicy | None
    # Mandatory coverage markers reject totals loaded for an earlier period.
    spending_day: date
    spending_month: date


class ReconciliationSnapshot(Contract):
    tenant_id: Identifier
    case_id: Identifier
    student_id: Identifier
    submission_allowed: bool
