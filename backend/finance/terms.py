"""Canonical digest of immutable payment terms (shared canonicalization with approvals)."""

import hashlib
import json
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from backend.contracts.models import PaymentTerms

HASH_EXCLUDED = frozenset({"terms_hash"})


def canonical_terms_hash(terms: PaymentTerms) -> str:
    payload = {
        name: _canonical_value(getattr(terms, name))
        for name in PaymentTerms.model_fields
        if name not in HASH_EXCLUDED
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def with_hash(terms: PaymentTerms) -> PaymentTerms:
    return terms.model_copy(update={"terms_hash": canonical_terms_hash(terms)})


def _canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    return value
