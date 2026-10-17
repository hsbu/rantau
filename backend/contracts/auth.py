"""Additive B-01 HTTP shapes approved on 2026-10-17; no client identity authority."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, SecretStr, field_validator

from backend.contracts.enums import Role
from backend.contracts.models import Contract, Identifier

SharedField = Literal["tuition_summary", "payment_summary", "case_summary"]
SHARED_FIELDS: frozenset[str] = frozenset({"tuition_summary", "payment_summary", "case_summary"})


class LoginRequest(Contract):
    username: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.-]+$")]
    password: SecretStr

    @field_validator("password")
    @classmethod
    def bounded_password(cls, value: SecretStr) -> SecretStr:
        if not 1 <= len(value.get_secret_value()) <= 128:
            raise ValueError("Invalid credential length")
        return value


class SessionSummary(Contract):
    authenticated: Literal[True] = True
    role: Role


class ConsentRequest(Contract):
    allowed_shared_fields: Annotated[frozenset[SharedField], Field(min_length=1, max_length=3)]
    expires_at: AwareDatetime


class ConsentSummary(ConsentRequest):
    sponsor_id: Identifier
