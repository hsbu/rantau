"""Declarative synthetic scenarios. Fixture numbers are authored assumptions, not real terms."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.contracts.enums import Currency

TUITION_UNIVERSITY_ID = "uni_cn_01"
OBLIGATION_ALIAS = "obl_2026_demo_01"
OBLIGATION_DUE_MINOR = 2_000_000
OBLIGATION_DUE_AT = datetime(2026, 11, 21, 9, tzinfo=UTC)
BENEFICIARY_ALIAS = "benef_uni_cn_01"
BENEFICIARY_FINGERPRINT = "synthetic-beneficiary-fingerprint"
POLICY_VERSION = "cn_demo_v1"
STUDENT_ID = "stu_001"
SPONSOR_ID = "par_001"
ROUTINE_THRESHOLD_MINOR = 5_000_000
ACCOUNT_TIMEZONE = "Asia/Jakarta"
QUOTE_ALIASES = {"mock_remit_a": "quote_001", "mock_remit_b": "quote_002"}


@dataclass(frozen=True)
class AccountSeed:
    alias: str
    owner_id: str
    balance_minor: int
    per_transfer_limit_minor: int
    daily_limit_minor: int
    monthly_limit_minor: int
    currency: Currency = Currency.IDR
    timezone: str = ACCOUNT_TIMEZONE


@dataclass(frozen=True)
class BeneficiarySeed:
    alias: str
    fingerprint: str
    verified: bool
    masked_display: str


SPONSOR_ACCOUNT = AccountSeed(
    "acct_idr_01", SPONSOR_ID, 150_000_000, 100_000_000, 150_000_000, 300_000_000
)
STUDENT_ACCOUNT = AccountSeed(
    "acct_idr_stu_01", STUDENT_ID, 60_000_000, 60_000_000, 60_000_000, 60_000_000
)
UNIVERSITY_BENEFICIARY = BeneficiarySeed(
    BENEFICIARY_ALIAS, BENEFICIARY_FINGERPRINT, True, "Fictional university •••• DEMO"
)
UNVERIFIED_BENEFICIARY = BeneficiarySeed(
    "benef_unverified_01", "forged-new-account-fingerprint", False, "Unverified account •••• 0000"
)


@dataclass(frozen=True)
class ScenarioSpec:
    id: str
    description: str
    accounts: tuple[AccountSeed, ...] = (SPONSOR_ACCOUNT, STUDENT_ACCOUNT)
    beneficiaries: tuple[BeneficiarySeed, ...] = (UNIVERSITY_BENEFICIARY,)
    quote_ttl_seconds: int = 900
    tags: frozenset[str] = field(default_factory=frozenset)


SCENARIOS = {
    spec.id: spec
    for spec in (
        ScenarioSpec("tuition_happy_path", "Sponsor-funded tuition with a verified university."),
        ScenarioSpec(
            "forged_beneficiary",
            "Adds an unverified payee that a forged instruction might name.",
            beneficiaries=(UNIVERSITY_BENEFICIARY, UNVERIFIED_BENEFICIARY),
        ),
        ScenarioSpec(
            "demo_long_quotes",
            "Happy path with 30-minute quotes for a recorded walkthrough.",
            quote_ttl_seconds=1800,
        ),
    )
}


def scenario(scenario_id: str) -> ScenarioSpec:
    try:
        return SCENARIOS[scenario_id]
    except KeyError:
        raise ValueError(f"Unknown scenario: {scenario_id}") from None
