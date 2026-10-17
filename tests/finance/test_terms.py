from datetime import timedelta, timezone

import pytest

from backend.contracts.models import PaymentTerms
from backend.finance.terms import canonical_terms_hash, with_hash
from tests.fixtures.data import INTENT

TERMS = PaymentTerms(**{name: getattr(INTENT, name) for name in PaymentTerms.model_fields})


def test_hash_is_a_lowercase_sha256_hex_and_ignores_the_stored_hash():
    digest = canonical_terms_hash(TERMS)
    assert len(digest) == 64 and digest == digest.lower()
    assert canonical_terms_hash(TERMS.model_copy(update={"terms_hash": "other"})) == digest


@pytest.mark.parametrize(
    "update",
    [
        {"source_total_minor": TERMS.source_total_minor + 1},
        {"destination_amount_minor": TERMS.destination_amount_minor + 1},
        {"beneficiary_id": "benef_other"},
        {"beneficiary_fingerprint": "other"},
        {"quote_id": "quote_other"},
        {"source_account_id": "acct_other"},
        {"intent_revision": 2},
        {"policy_version": "cn_demo_v2"},
    ],
)
def test_any_term_change_changes_the_hash(update):
    assert canonical_terms_hash(TERMS.model_copy(update=update)) != canonical_terms_hash(TERMS)


def test_equivalent_instants_in_different_zones_hash_identically():
    shifted = TERMS.quote_expiry.astimezone(timezone(timedelta(hours=7)))
    assert canonical_terms_hash(TERMS.model_copy(update={"quote_expiry": shifted})) == (
        canonical_terms_hash(TERMS)
    )


def test_with_hash_stamps_the_computed_digest():
    stamped = with_hash(TERMS)
    assert stamped.terms_hash == canonical_terms_hash(TERMS)
