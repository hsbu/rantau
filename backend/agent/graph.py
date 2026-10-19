"""Fixed read/triage paths and explicit, protected tuition continuation commands."""

from collections.abc import Hashable
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from backend.agent.actions import TuitionActions, action_command, action_reply, proposal_of
from backend.agent.classifier import (
    ClassificationUnavailable,
    IntentClassification,
    IntentClassifier,
)
from backend.agent.conversation import conversational_reply
from backend.agent.protection import AgentProtection
from backend.agent.recovery import RecoveryWorkflow, payment_selection_command, recovery_command
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
        actions: TuitionActions | None = None,
        recovery: RecoveryWorkflow | None = None,
    ) -> None:
        self.conversations = conversations if conversations is not None else InMemoryConversations()
        self.actions = actions
        self.recovery = recovery
        self.protection = AgentProtection(actions) if actions else None
        self.tools = tools

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
            elif intent in {Intent.TRACK, Intent.RECOVER} and self.recovery is not None:
                response, selected = await self.recovery.investigate(
                    state["message"], conversation.recovery, state["actor"], intent
                )
                conversation = conversation.model_copy(update={"recovery": selected})
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
                    message=conversational_reply(state["classification"], state["conversation"]),
                )
            }

        def unavailable(state: GraphState) -> GraphState:
            return {
                "response": AgentResponse(
                    run_id="pending",
                    requested_action=None,
                    message=(
                        "I couldn’t understand your request because the service is unavailable. "
                        "No payment was requested. Please try again later."
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
            if self.recovery and payment_selection_command(message):
                return action_reply(
                    "Use a current conversation to list and select scoped payments.",
                    "list_student_payments",
                ).model_copy(update={"run_id": f"run_{uuid4().hex}"})
            if self.recovery and recovery_command(message):
                return self.recovery.reply(
                    "Select a payment in a current conversation before recovery submission/recheck."
                ).model_copy(update={"run_id": f"run_{uuid4().hex}"})
            if self.actions and action_command(message):
                return action_reply(
                    "A current conversation and reviewed tuition preview are "
                    "required before confirmation.",
                    "clarify_tuition",
                ).model_copy(update={"run_id": f"run_{uuid4().hex}"})
            response, _ = await self._turn(message, actor, ConversationState())
            return response
        key = ConversationKey(
            tenant_id=actor.tenant_id,
            actor_id=actor.actor_id,
            session_id=actor.session_id,
            conversation_id=conversation_id,
        )
        async with self.conversations.turn(key) as session:
            command = action_command(message) if self.actions else None
            recovery = recovery_command(message) if self.recovery else None
            selection = payment_selection_command(message) if self.recovery else None
            guarded = None
            if self.protection is not None:
                guarded = await self.protection.check(message, actor, key, session.state.tuition)
            if guarded is not None:
                response = guarded.model_copy(update={"run_id": f"run_{uuid4().hex}"})
                updated = session.state
            elif selection:
                assert self.recovery is not None
                intent = (
                    Intent.RECOVER
                    if session.state.active_intent == Intent.RECOVER
                    else Intent.TRACK
                )
                response, selected = await self.recovery.select_payment(
                    selection, session.state.recovery, actor, intent
                )
                updated = session.state.model_copy(
                    update={"recovery": selected, "active_intent": intent}
                )
                response = response.model_copy(update={"run_id": f"run_{uuid4().hex}"})
            elif recovery:
                assert self.recovery is not None
                response, selected = await self.recovery.handle(
                    recovery, session.state.recovery, actor
                )
                updated = session.state.model_copy(
                    update={"recovery": selected, "active_intent": Intent.RECOVER}
                )
                response = response.model_copy(update={"run_id": f"run_{uuid4().hex}"})
            elif command:
                updated = session.state
                proposal = proposal_of(updated.tuition)
                if updated.active_intent not in {Intent.TUITION, Intent.VERIFY_MESSAGE} or (
                    proposal is None
                ):
                    response = action_reply(
                        "Review a complete tuition preview first, then say 'confirm tuition'.",
                        "clarify_tuition",
                    )
                else:
                    assert self.actions is not None
                    if command == "REQUEST":
                        preview, fresh = await self.tools.plan_tuition(
                            TuitionInput(), updated.tuition, actor
                        )
                        updated = updated.model_copy(update={"tuition": fresh})
                        if proposal_of(fresh) != proposal or not any(
                            e.tool == "build_tuition_preview" and e.status == "OK"
                            for e in preview.tool_events
                        ):
                            response = preview
                        else:
                            response = await self.actions.handle(command, key, proposal, actor)
                    else:
                        response = await self.actions.handle(command, key, proposal, actor)
                response = response.model_copy(update={"run_id": f"run_{uuid4().hex}"})
            else:
                response, updated = await self._turn(message, actor, session.state)
                if self.actions and any(
                    e.tool == "build_tuition_preview" and e.status == "OK"
                    for e in response.tool_events
                ):
                    response = response.model_copy(
                        update={
                            "message": response.message
                            + "\n\n**Next step:** say `confirm tuition` to save this request "
                            "and request the funding owner’s approval. "
                            "This does not send funds yet."
                        }
                    )
            session.state = updated
            session.response = response
            return response

    async def _turn(
        self,
        message: str,
        actor: ActorContext,
        conversation: ConversationState,
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
