"""Typed trust facts and advisory findings for fraud assessment."""

from enum import StrEnum
from typing import Protocol

from backend.contracts.models import Contract


class AdvisorySignal(StrEnum):
    URGENCY = "URGENCY"
    SECRECY = "SECRECY"
    IMPERSONATION = "IMPERSONATION"
    EMERGENCY_REQUEST = "EMERGENCY_REQUEST"
    BENEFICIARY_CHANGE = "BENEFICIARY_CHANGE"
    PROMPT_INJECTION = "PROMPT_INJECTION"


class HardFinding(StrEnum):
    BENEFICIARY_UNVERIFIED = "BENEFICIARY_UNVERIFIED"
    BENEFICIARY_MISMATCH = "BENEFICIARY_MISMATCH"
    BENEFICIARY_CHANGE_REQUESTED = "BENEFICIARY_CHANGE_REQUESTED"


class TrustedFraudFacts(Contract):
    """Server-loaded registry facts; never construct from message/model output."""

    beneficiary_verified: bool
    beneficiary_matches_current_intent: bool
    beneficiary_change_requested: bool


class SemanticFraudSignals(Contract):
    """Constrained model output. These signals cannot authorize or release a hold."""

    indicators: tuple[AdvisorySignal, ...]


class SemanticFraudClassifier(Protocol):
    async def classify(self, message: str) -> SemanticFraudSignals: ...
