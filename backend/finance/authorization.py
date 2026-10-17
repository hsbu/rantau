"""Run the transaction-bound gate from synchronous service code."""

import asyncio
from collections.abc import Callable

from backend.authz.policy_repository import PolicyConnection
from backend.contracts.models import ActionIntent, ActorContext, PolicyDecision
from backend.contracts.ports import AuthorizationPort

GateFactory = Callable[[PolicyConnection], AuthorizationPort]


def evaluate_gate(
    gate: GateFactory, connection: PolicyConnection, actor: ActorContext, action: ActionIntent
) -> PolicyDecision:
    """The adapter is async in signature only; services call it from a worker thread."""
    return asyncio.run(gate(connection).evaluate(actor, action))
