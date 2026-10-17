"""Canonical immutable-term digest shared by intent creation and owner approval."""

import hashlib
import json
from datetime import UTC, datetime
from enum import Enum

from backend.contracts.models import PaymentTerms


def canonical_terms_hash(terms: PaymentTerms) -> str:
    values: dict[str, object] = {}
    for name in PaymentTerms.model_fields:
        if name == "terms_hash":
            continue
        value = getattr(terms, name)
        if isinstance(value, datetime):
            if value.utcoffset() is None:
                raise ValueError("Terms require aware timestamps")
            value = value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        elif isinstance(value, Enum):
            value = value.value
        values[name] = value
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
