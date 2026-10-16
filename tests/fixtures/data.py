"""Reproducible synthetic identities and quotes with an explicit clock."""

from datetime import UTC, datetime, timedelta

from backend.contracts.enums import Currency, PaymentState, Role, Tier, TuitionState
from backend.contracts.models import (
    ActorContext,
    FxQuote,
    PaymentIntent,
    PaymentResult,
    TuitionObligation,
    UniversityPolicy,
)

NOW = datetime(2026, 11, 1, 9, tzinfo=UTC)
ACTOR = ActorContext(
    actor_id="stu_001",
    tenant_id="demo_001",
    session_id="session_student",
    role=Role.STUDENT,
    scopes=frozenset({"student:read", "payment:propose"}),
)
OBLIGATION = TuitionObligation(
    id="obl_2026_demo_01",
    student_id="stu_001",
    university_id="uni_cn_01",
    amount_due_minor=2_000_000,
    posted_minor=0,
    balance_minor=2_000_000,
    due_at=NOW + timedelta(days=20),
    policy_id="cn_demo_v1",
    state=TuitionState.UNPAID,
)
QUOTE = FxQuote(
    id="quote_001",
    provider="Synthetic route A",
    source_currency=Currency.IDR,
    destination_currency=Currency.CNY,
    source_principal_minor=46_000_000,
    fee_minor=25_000,
    source_total_minor=46_025_000,
    destination_amount_minor=2_000_000,
    rate="0.0004347826086956521739130435",
    expires_at=NOW + timedelta(minutes=15),
    estimated_delivery_at=NOW + timedelta(days=1),
)
QUOTE_B = FxQuote(
    id="quote_002",
    provider="Synthetic route B",
    source_currency=Currency.IDR,
    destination_currency=Currency.CNY,
    source_principal_minor=46_000_000,
    fee_minor=50_000,
    source_total_minor=46_050_000,
    destination_amount_minor=2_000_000,
    rate=QUOTE.rate,
    expires_at=QUOTE.expires_at,
    estimated_delivery_at=QUOTE.estimated_delivery_at,
)
POLICY = UniversityPolicy(
    id="cn_demo_v1",
    university_id="uni_cn_01",
    term_id="term_demo_2026",
    version="cn_demo_v1",
    required_references=("student ID", "full name"),
    posting_window_hours=48,
    partial_payment_allowed=False,
    topup_allowed=False,
    source_url="https://example.invalid/rantau/synthetic-policy",
    verified_at=NOW,
    effective_from=NOW - timedelta(days=1),
    effective_to=NOW + timedelta(days=60),
    certainty="SYNTHETIC",
)
INTENT = PaymentIntent(
    id="intent_001",
    intent_id="intent_001",
    intent_revision=1,
    funding_owner_id="par_001",
    source_account_id="acct_idr_01",
    beneficiary_id="benef_uni_cn_01",
    beneficiary_fingerprint="synthetic-beneficiary-fingerprint",
    purpose="TUITION",
    obligation_id=OBLIGATION.id,
    source_currency=Currency.IDR,
    destination_currency=Currency.CNY,
    source_total_minor=QUOTE.source_total_minor,
    destination_amount_minor=QUOTE.destination_amount_minor,
    quote_id=QUOTE.id,
    quote_expiry=QUOTE.expires_at,
    policy_version=POLICY.version,
    terms_hash="synthetic:not-valid-authorization",
    requested_by=ACTOR.actor_id,
    tier=Tier.T2,
    state=PaymentState.AWAITING_APPROVAL,
)
PAYMENT = PaymentResult(
    payment_id="transfer_001",
    intent_id=INTENT.id,
    provider_reference="sim_ref_001",
    transfer_status=PaymentState.DELIVERED,
    receipt_reference="receipt_001",
    audit_event_id="audit_001",
)
