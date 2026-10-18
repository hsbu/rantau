"""Scoped agent HTTP seam; trusted services are deliberately not replaced by fakes."""

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.agent.graph import AgentGraph
from backend.contracts.http import AgentMessage, AgentResponse
from backend.contracts.models import ActorContext, ScopeDenied, ServiceUnavailable
from backend.dependencies import auth_settings, verified_actor
from backend.kb.search import research_deadline


class RunRepository(Protocol):
    """A real adapter must persist selected diagnostics with actor/session scope."""

    async def put(self, response: AgentResponse, actor: ActorContext) -> None: ...

    async def get(self, run_id: str, actor: ActorContext) -> AgentResponse: ...


@dataclass(frozen=True)
class AgentServices:
    graph: AgentGraph
    runs: RunRepository


async def agent_services(request: Request) -> AsyncIterator[AgentServices]:
    from backend.agent.actions import action_command
    from backend.agent.recovery import payment_selection_command, recovery_command
    from backend.agent.wiring import configured_agent_services

    require_classifier = request.method == "POST"
    if require_classifier:
        try:
            body = await request.json()
        except ValueError:
            body = None
        if isinstance(body, dict) and isinstance(body.get("message"), str):
            require_classifier = not (
                action_command(body["message"])
                or recovery_command(body["message"])
                or payment_selection_command(body["message"])
            )
    async with configured_agent_services(require_classifier=require_classifier) as services:
        yield services


Actor = Annotated[ActorContext, Depends(verified_actor)]
Services = Annotated[AgentServices, Depends(agent_services)]
router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


@router.post("/messages", response_model=AgentResponse)
async def message(
    body: AgentMessage, actor: Actor, services: Services, request: Request
) -> AgentResponse:
    if (services.graph.actions is not None or services.graph.recovery is not None) and (
        request.headers.get("origin") != auth_settings().auth_trusted_origin
    ):
        raise HTTPException(403, detail={"code": "UNTRUSTED_ORIGIN"})
    token = research_deadline.set(time.monotonic() + 21)
    try:
        result = await services.graph.run(body.message, actor, body.conversation_id)
        await services.runs.put(result, actor)
        return result
    except ScopeDenied:
        raise HTTPException(status_code=404, detail="Resource unavailable") from None
    except ServiceUnavailable:
        raise HTTPException(status_code=503, detail="Trusted service unavailable") from None
    finally:
        research_deadline.reset(token)


@router.get("/runs/{run_id}", response_model=AgentResponse)
async def run_status(run_id: str, actor: Actor, services: Services) -> AgentResponse:
    try:
        return await services.runs.get(run_id, actor)
    except ScopeDenied:
        raise HTTPException(status_code=404, detail="Resource unavailable") from None
    except ServiceUnavailable:
        raise HTTPException(status_code=503, detail="Trusted service unavailable") from None
