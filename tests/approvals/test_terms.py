from datetime import timedelta, timezone

import pytest
from pydantic import ValidationError

from backend.contracts.authority import MandateRequest
from backend.contracts.models import PaymentTerms
from backend.contracts.terms import canonical_terms_hash
from tests.fixtures.data import INTENT, NOW


def test_digest_is_stable_and_normalizes_utc():
    digest = canonical_terms_hash(INTENT)
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
    assert digest == canonical_terms_hash(
        INTENT.model_copy(update={"terms_hash": "ignored", "tier": "T0"})
    )
    assert digest == canonical_terms_hash(
        INTENT.model_copy(
            update={"quote_expiry": INTENT.quote_expiry.astimezone(timezone(timedelta(hours=7)))}
        )
    )


@pytest.mark.parametrize("field", [f for f in PaymentTerms.model_fields if f != "terms_hash"])
def test_digest_binds_every_immutable_term(field):
    value = getattr(INTENT, field)
    replacement = (
        value + timedelta(seconds=1)
        if field == "quote_expiry"
        else value + 1
        if isinstance(value, int)
        else "changed"
    )
    assert canonical_terms_hash(
        INTENT.model_copy(update={field: replacement})
    ) != canonical_terms_hash(INTENT)


def mandate_data():
    return dict(
        source_account_id="acct_idr_01",
        delegate_id="stu_001",
        beneficiary_id="benef_stu_001",
        currency="IDR",
        per_transfer_limit_minor=100,
        daily_limit_minor=200,
        monthly_limit_minor=1000,
        starts_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )


@pytest.mark.parametrize(
    "change",
    [
        {"role": "SPONSOR"},
        {"owner_id": "other"},
        {"approved": True},
        {"beneficiary_fingerprint": "forged"},
        {"timezone": "UTC"},
        {"per_transfer_limit_minor": 1.5},
        {"daily_limit_minor": True},
        {"per_transfer_limit_minor": -1},
        {"daily_limit_minor": 1},
        {"expires_at": NOW},
        {"starts_at": "2026-11-01T09:00:00"},
    ],
)
def test_mandate_input_cannot_supply_authority_or_inexact_limits(change):
    with pytest.raises(ValidationError):
        MandateRequest.model_validate(mandate_data() | change)


def test_mandate_is_allowance_only():
    assert MandateRequest.model_validate(mandate_data()).per_transfer_limit_minor == 100
    with pytest.raises(ValidationError):
        MandateRequest.model_validate(mandate_data() | {"purpose": "TUITION"})
