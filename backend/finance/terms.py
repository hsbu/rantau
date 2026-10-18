"""Canonical digest of immutable payment terms (shared canonicalization with approvals)."""

from backend.contracts.models import PaymentTerms
from backend.contracts.terms import canonical_terms_hash as canonical_terms_hash


def with_hash(terms: PaymentTerms) -> PaymentTerms:
    return terms.model_copy(update={"terms_hash": canonical_terms_hash(terms)})
