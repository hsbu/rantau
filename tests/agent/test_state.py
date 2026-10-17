import asyncio

import pytest
from pydantic import ValidationError

from backend.agent.state import ConversationKey, InMemoryConversations, TuitionDraft, TuitionInput
from backend.contracts.enums import Intent
from backend.contracts.models import ServiceUnavailable
from tests.agent.test_tuition import key


@pytest.mark.parametrize(
    "changes",
    [
        {"obligation_option": 0},
        {"funding_option": True},
        {"quote_option": 101},
        {"amount_cny": "0.001"},
        {"amount_cny": "NaN"},
        {"approved": True},
        {"amount_cny": "100", "full_balance": True},
        {"role": "SPONSOR"},
    ],
)
def test_interpretation_is_bounded_and_cannot_carry_authority(changes):
    with pytest.raises(ValidationError):
        TuitionInput.model_validate(changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": "another_tenant"},
        {"actor_id": "another_student"},
        {"session_id": "another_session"},
        {"conversation_id": "another_conversation"},
    ],
)
async def test_memory_is_namespaced_by_tenant_student_session_and_conversation(changes):
    store = InMemoryConversations()
    async with store.turn(key()) as session:
        session.state = session.state.model_copy(
            update={
                "active_intent": Intent.TUITION,
                "tuition": TuitionDraft(source_account_id="acct_private"),
            }
        )
    async with store.turn(key(**changes)) as other:
        assert other.state.active_intent is None
        assert other.state.tuition.source_account_id is None


async def test_memory_expires_and_capacity_is_bounded():
    timer = [0.0]
    store = InMemoryConversations(capacity=1, ttl_seconds=5, clock=lambda: timer[0])
    async with store.turn(key()) as session:
        session.state = session.state.model_copy(update={"active_intent": Intent.TUITION})
    with pytest.raises(ServiceUnavailable):
        async with store.turn(key("another")):
            pass
    timer[0] = 5
    async with store.turn(key()) as refreshed:
        assert refreshed.state.active_intent is None


async def test_simultaneous_turns_on_one_conversation_are_serialized():
    store = InMemoryConversations()
    acquired = asyncio.Event()
    seen = []

    async def first():
        async with store.turn(key()) as session:
            acquired.set()
            await asyncio.sleep(0)
            session.state = session.state.model_copy(update={"active_intent": Intent.TUITION})

    async def second():
        await acquired.wait()
        async with store.turn(key()) as session:
            seen.append(session.state.active_intent)

    await asyncio.gather(first(), second())
    assert seen == [Intent.TUITION]


def test_memory_key_rejects_unbounded_or_invalid_client_identifier():
    with pytest.raises(ValidationError):
        ConversationKey.model_validate(key().model_dump() | {"conversation_id": "../private"})
