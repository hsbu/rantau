"""Fixed LangGraph paths with scoped conversation drafts and read-only capabilities."""

from collections.abc import Hashable
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from backend.agent.classifier import (
    ClassificationUnavailable,
    IntentClassification,
    IntentClassifier,
)
from backend.agent.state import (
    ConversationKey,
    ConversationState,
    ConversationStore,
    InMemoryConversations,
    TuitionInput,
)
from backend.agent.tools import AgentTools
from backend.contracts.enums import Intent, Role
from backend.contracts.http import AgentResponse, ToolEvent
from backend.contracts.models import ActorContext, ScopeDenied


class GraphState(TypedDict, total=False):
    message: str
    actor: ActorContext
    classification: IntentClassification
    unavailable: bool
    response: AgentResponse
    conversation: ConversationState


class AgentGraph:
    def __init__(
        self,
        classifier: IntentClassifier,
        tools: AgentTools,
        *,
        conversations: ConversationStore | None = None,
    ) -> None:
        self.conversations = conversations if conversations is not None else InMemoryConversations()

        async def classify(state: GraphState) -> GraphState:
            try:
                context = state["conversation"]
                message = state["message"]
                if context.active_intent is not None:
                    message = context.model_context() + "\nCurrent untrusted message:\n" + message
                result = await classifier.classify(message)
                return {"classification": result}
            except ClassificationUnavailable:
                return {"unavailable": True}

        def route(state: GraphState) -> str:
            if state.get("unavailable"):
                return "unavailable"
            classification = state["classification"]
            if classification.needs_clarification or classification.intent is None:
                return "clarify"
            return classification.intent.value

        async def handle(state: GraphState) -> GraphState:
            classification = state["classification"]
            intent = classification.intent
            assert intent is not None
            conversation = state["conversation"]
            if intent == Intent.TUITION:
                response, tuition = await tools.plan_tuition(
                    classification.tuition or TuitionInput(), conversation.tuition, state["actor"]
                )
                conversation = conversation.model_copy(update={"tuition": tuition})
            else:
                response = await tools.safe_handle(intent, state["message"], state["actor"])
            return {
                "response": response,
                "conversation": conversation.model_copy(update={"active_intent": intent}),
            }

        def clarify(state: GraphState) -> GraphState:
            return {
                "response": AgentResponse(
                    run_id="pending",
                    requested_action=None,
                    message=(
                        "Do you need tuition, allowance, payment tracking, recovery, "
                        "policy, or message verification?"
                    ),
                )
            }

        def unavailable(state: GraphState) -> GraphState:
            return {
                "response": AgentResponse(
                    run_id="pending",
                    requested_action=None,
                    message=(
                        "Intent classification is unavailable. "
                        "No financial action was taken. Try again later."
                    ),
                    tool_events=(ToolEvent(tool="classify_intent", status="UNAVAILABLE"),),
                )
            }

        builder = StateGraph(GraphState)
        builder.add_node("classify", classify)
        builder.add_node("clarify", clarify)
        builder.add_node("unavailable", unavailable)
        builder.add_edge(START, "classify")
        paths: dict[Hashable, str] = {intent.value: intent.value for intent in Intent}
        paths.update({"clarify": "clarify", "unavailable": "unavailable"})
        builder.add_conditional_edges("classify", route, paths)
        for intent in Intent:
            builder.add_node(intent.value, handle)
            builder.add_edge(intent.value, END)
        builder.add_edge("clarify", END)
        builder.add_edge("unavailable", END)
        self.graph = builder.compile()

    async def run(
        self, message: str, actor: ActorContext, conversation_id: str | None = None
    ) -> AgentResponse:
        if actor.role != Role.STUDENT or "student:read" not in actor.scopes:
            raise ScopeDenied("Resource unavailable")
        if conversation_id is None:
            response, _ = await self._turn(message, actor, ConversationState())
            return response
        key = ConversationKey(
            tenant_id=actor.tenant_id,
            actor_id=actor.actor_id,
            session_id=actor.session_id,
            conversation_id=conversation_id,
        )
        async with self.conversations.turn(key) as session:
            response, updated = await self._turn(message, actor, session.state)
            session.state = updated
            session.response = response
            return response

    async def _turn(
        self, message: str, actor: ActorContext, conversation: ConversationState
    ) -> tuple[AgentResponse, ConversationState]:
        output = await self.graph.ainvoke(
            {"message": message, "actor": actor, "conversation": conversation},
            config={"recursion_limit": 5},
        )
        response = AgentResponse.model_validate(output["response"])
        return (
            response.model_copy(update={"run_id": f"run_{uuid4().hex}"}),
            ConversationState.model_validate(output["conversation"]),
        )
