"""Typed intent classification is interpretation, never authorization."""

from typing import Protocol, Self

from pydantic import model_validator

from backend.agent.state import TuitionInput
from backend.contracts.enums import Intent
from backend.contracts.models import Contract


class IntentClassification(Contract):
    intent: Intent | None
    needs_clarification: bool
    tuition: TuitionInput | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.intent is None and not self.needs_clarification:
            raise ValueError("An unknown intent requires clarification")
        return self


class ClassificationUnavailable(Exception):
    """Classifier failed; the graph must not guess a financial action."""


class IntentClassifier(Protocol):
    async def classify(self, message: str) -> IntentClassification: ...
