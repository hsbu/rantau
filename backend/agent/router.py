"""Scoped agent HTTP seam; trusted services are deliberately not replaced by fakes."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.agent.graph import AgentGraph
from backend.contracts.http import AgentMessage, AgentResponse
from backend.contracts.models import ActorContext, ScopeDenied, ServiceUnavailable
from backend.dependencies import verified_actor


class RunRepository(Protocol):
    """A real adapter must persist selected diagnostics with actor/session scope."""

    async def put(self, response: AgentResponse, actor: ActorContext) -> None: ...

    async def get(self, run_id: str, actor: ActorContext) -> AgentResponse: ...


@dataclass(frozen=True)
class AgentServices:
    graph: AgentGraph
    runs: RunRepository


async def agent_services(request: Request) -> AsyncIterator[AgentServices]:
    from backend.agent.wiring import configured_agent_services

    async with configured_agent_services(require_classifier=request.method == "POST") as services:
        yield services


Actor = Annotated[ActorContext, Depends(verified_actor)]
Services = Annotated[AgentServices, Depends(agent_services)]
router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


@router.post("/messages", response_model=AgentResponse)
async def message(body: AgentMessage, actor: Actor, services: Services) -> AgentResponse:
    try:
        result = await services.graph.run(body.message, actor, body.conversation_id)
        await services.runs.put(result, actor)
        return result
    except ScopeDenied:
        raise HTTPException(status_code=404, detail="Resource unavailable") from None
    except ServiceUnavailable:
        raise HTTPException(status_code=503, detail="Trusted service unavailable") from None


@router.get("/runs/{run_id}", response_model=AgentResponse)
async def run_status(run_id: str, actor: Actor, services: Services) -> AgentResponse:
    try:
        return await services.runs.get(run_id, actor)
    except ScopeDenied:
        raise HTTPException(status_code=404, detail="Resource unavailable") from None
    except ServiceUnavailable:
        raise HTTPException(status_code=503, detail="Trusted service unavailable") from None
