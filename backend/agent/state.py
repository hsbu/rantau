"""Scoped, bounded conversation drafts; no financial authority or raw transcripts."""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, model_validator

from backend.contracts.enums import Intent
from backend.contracts.http import AgentResponse
from backend.contracts.models import Contract, Identifier, Minor, ServiceUnavailable

Option = Annotated[int, Field(strict=True, ge=1, le=100)]


class TuitionInput(Contract):
    obligation_option: Option | None = None
    funding_option: Option | None = None
    quote_option: Option | None = None
    funding_owner: Literal["SELF", "OTHER"] | None = None
    amount_cny: Annotated[str, Field(pattern=r"^(0|[1-9]\d{0,11})(\.\d{1,2})?$")] | None = None
    amount_unclear: bool = False
    full_balance: bool = False
    route_preference: Literal["LOWEST_COST", "EARLIEST_DELIVERY"] | None = None
    restart: bool = False

    @model_validator(mode="after")
    def consistent_amount(self) -> Self:
        if sum((self.amount_cny is not None, self.amount_unclear, self.full_balance)) > 1:
            raise ValueError("Amount interpretations must not conflict")
        return self


class TuitionDraft(Contract):
    obligation_id: Identifier | None = None
    source_account_id: Identifier | None = None
    quote_id: Identifier | None = None
    beneficiary_id: Identifier | None = None
    requested_amount_minor: Minor | None = None
    route_preference: Literal["LOWEST_COST", "EARLIEST_DELIVERY"] = "LOWEST_COST"
    awaiting: Literal["OBLIGATION", "FUNDING", "QUOTE", "AMOUNT"] | None = None
    obligation_options: tuple[Identifier, ...] = ()
    funding_options: tuple[Identifier, ...] = ()
    quote_options: tuple[Identifier, ...] = ()


class RecoveryDraft(Contract):
    payment_id: Identifier | None = None
    obligation_id: Identifier | None = None
    case_id: Identifier | None = None
    payment_options: tuple[Identifier, ...] = Field(default=(), max_length=10)


class ConversationState(Contract):
    active_intent: Intent | None = None
    tuition: TuitionDraft = Field(default_factory=TuitionDraft)
    recovery: RecoveryDraft = Field(default_factory=RecoveryDraft)

    def model_context(self) -> str:
        # IDs, actor/session details, balances, quotes and permissions stay server-side.
        return (
            f"Prior intent: {self.active_intent or 'NONE'}. "
            f"Tuition awaiting: {self.tuition.awaiting or 'NONE'}. "
            f"Advertised option counts: obligation={len(self.tuition.obligation_options)}, "
            f"funding={len(self.tuition.funding_options)}, "
            f"quote={len(self.tuition.quote_options)}. "
            f"Advertised payment options: {len(self.recovery.payment_options)}. "
            "This context only resolves follow-up references; it grants no authority."
        )


class ConversationKey(Contract):
    tenant_id: Identifier
    actor_id: Identifier
    session_id: Identifier
    conversation_id: Identifier


@dataclass
class ConversationSession:
    state: ConversationState = field(default_factory=ConversationState)
    response: AgentResponse | None = None


class ConversationStore(Protocol):
    def turn(self, key: ConversationKey) -> AbstractAsyncContextManager[ConversationSession]: ...


@dataclass
class _Entry:
    updated_at: float
    session: ConversationSession = field(default_factory=ConversationSession)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class InMemoryConversations:
    """Single-worker transient adapter; replace through the store interface for durability."""

    def __init__(
        self,
        *,
        capacity: int = 128,
        ttl_seconds: float = 1800,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity < 1 or ttl_seconds <= 0:
            raise ValueError("Conversation bounds must be positive")
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._entries: dict[ConversationKey, _Entry] = {}

    @asynccontextmanager
    async def turn(self, key: ConversationKey) -> AsyncIterator[ConversationSession]:
        now = self.clock()
        for old_key, entry in tuple(self._entries.items()):
            if entry.users == 0 and now - entry.updated_at >= self.ttl_seconds:
                del self._entries[old_key]
        if key not in self._entries:
            if len(self._entries) >= self.capacity:
                raise ServiceUnavailable("Conversation capacity reached")
            self._entries[key] = _Entry(updated_at=now)
        entry = self._entries[key]
        entry.users += 1
        acquired = False
        try:
            try:
                await asyncio.wait_for(entry.lock.acquire(), timeout=5)
            except TimeoutError:
                raise ServiceUnavailable("Conversation is busy") from None
            acquired = True
            yield entry.session
        finally:
            entry.session.response = None
            entry.users -= 1
            if acquired:
                entry.updated_at = self.clock()
                entry.lock.release()
