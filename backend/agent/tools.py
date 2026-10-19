"""Read-only intent handlers with selected display fields and safe fallbacks."""

import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from pydantic import ValidationError

from backend.agent.explanations import explain_tuition_record
from backend.agent.guidance import explain_assessment
from backend.agent.state import TuitionDraft, TuitionInput
from backend.agent.tuition import TuitionPlanner
from backend.contracts.enums import Intent, PaymentState, TuitionState
from backend.contracts.http import AgentResponse, ResourceReference, ToolEvent
from backend.contracts.models import ActorContext, ScopeDenied, ServiceUnavailable
from backend.contracts.ports import AgentReadPort
from backend.kb.catalog import load_bundle
from backend.kb.guidance import explain_policy, known_policy
from backend.kb.records import KnowledgeBundle
from backend.kb.research import OfficialSourceLookup, explain_research, research_event_status


class AgentTools:
    def __init__(
        self,
        port: AgentReadPort,
        clock: Callable[[], datetime] | None = None,
        *,
        kb_loader: Callable[[], KnowledgeBundle] = load_bundle,
        beneficiary_map: Mapping[str, str] | None = None,
        research: OfficialSourceLookup | None = None,
    ) -> None:
        self.port = port
        self.clock = clock or (lambda: datetime.now(UTC))
        self.kb_loader = kb_loader
        self.research = research
        self.tuition = TuitionPlanner(port, self.clock, self.knowledge, beneficiary_map)

    async def plan_tuition(
        self, inputs: TuitionInput, draft: TuitionDraft, actor: ActorContext
    ) -> tuple[AgentResponse, TuitionDraft]:
        try:
            response, updated = await self.tuition.plan(inputs, draft, actor)
            if self.research and any(
                e.tool == "get_university_payment_policy" and e.status == "PENDING"
                for e in response.tool_events
            ):
                policy = await self.port.policy(actor)
                guidance, event = await self.shortfall_guidance(policy.university_id)
                response = response.model_copy(
                    update={
                        "message": response.message + "\n" + guidance,
                        "tool_events": response.tool_events + (event,),
                    }
                )
            return response, updated
        except ServiceUnavailable:
            return (
                AgentResponse(
                    run_id="pending",
                    requested_action=Intent.TUITION,
                    message="Trusted service unavailable. No financial action was taken.",
                    tool_events=(ToolEvent(tool="domain_read", status="UNAVAILABLE"),),
                ),
                draft,
            )

    def knowledge(self) -> KnowledgeBundle | None:
        try:
            return self.kb_loader()
        except (OSError, UnicodeError, ValidationError):
            return None

    async def shortfall_guidance(self, university_id: str) -> tuple[str, ToolEvent]:
        # Only this fictional demo has a curated procedural-inspiration collection.
        # Never infer a real institution or accept source URLs from user/model input.
        enabled = self.research is not None and university_id == "uni_cn_01"
        result = await self.research.lookup() if enabled and self.research else None
        return explain_research(result), ToolEvent(
            tool="lookup_shortfall_sources", status=research_event_status(result)
        )

    async def handle(self, intent: Intent, message: str, actor: ActorContext) -> AgentResponse:
        prefix = "Simulated Rantau guidance. "
        events: tuple[ToolEvent, ...] = ()
        resources: tuple[ResourceReference, ...] = ()
        if intent == Intent.ASK_POLICY:
            policy = await self.port.policy(actor)
            bundle = self.knowledge()
            now = self.clock()
            events = (
                ToolEvent(
                    tool="get_university_payment_policy",
                    status="OK" if known_policy(policy, bundle, now) else "PENDING",
                ),
            )
            text = explain_policy(policy, bundle, now)
            if bundle is None or not any(
                claim.key == "topup_allowed" and claim.support == "EXPLICIT"
                for claim in bundle.reference.claims
            ):
                guidance, event = await self.shortfall_guidance(policy.university_id)
                text += "\n" + guidance
                events += (event,)
            resources = (ResourceReference(kind="policy", id=policy.id),)
        elif intent == Intent.TUITION:
            response, _ = await self.plan_tuition(TuitionInput(), TuitionDraft(), actor)
            return response
        elif intent == Intent.ALLOWANCE:
            permissions = await self.port.permissions(actor)
            events = (ToolEvent(tool="get_account_permissions", status="OK"),)
            eligible = any(
                "ALLOWANCE" in permission.permitted_purposes for permission in permissions
            )
            text = (
                "Allowance planning is available. Specify the amount "
                "and verified student recipient. A trusted service must check "
                "the owner's approval or active mandate before execution."
                if eligible
                else "No eligible allowance funding permission is available."
            )
        elif intent in (Intent.TRACK, Intent.RECOVER):
            references = re.findall(r"\btransfer_[A-Za-z0-9_-]+\b", message)
            if len(set(references)) != 1:
                text = "Select one payment reference, such as transfer_001, to check."
            else:
                payment = await self.port.payment_status(references[0], actor)
                events = (
                    ToolEvent(
                        tool="get_payment_status", status="OK", resource_id=payment.payment_id
                    ),
                )
                resources = (ResourceReference(kind="payment", id=payment.payment_id),)
                if payment.transfer_status == PaymentState.OUTCOME_UNKNOWN:
                    text = (
                        "Provider outcome is unknown. "
                        "Recheck the original reference before any retry."
                    )
                elif payment.transfer_status != PaymentState.DELIVERED:
                    text = (
                        f"Provider state: {payment.transfer_status.value}. "
                        "Tuition posting is unverified."
                    )
                else:
                    obligations = await self.port.obligations(actor)
                    events += (ToolEvent(tool="get_tuition_obligation", status="OK"),)
                    # Do not guess the payment's obligation from a student's unrelated records.
                    text = (
                        "Provider state: DELIVERED. "
                        "University posting for this payment is unverified. "
                        "Link the payment to its obligation before claiming tuition completion."
                    )
                    if len(obligations) == 1:
                        obligation = obligations[0]
                        text += f" Your obligation state is {obligation.state.value}."
                        if obligation.state != TuitionState.PAID:
                            text += (
                                " Do not make a duplicate payment; "
                                "review posting or reconciliation evidence."
                            )
                            if intent == Intent.RECOVER:
                                text += "\n" + explain_tuition_record(obligation)
                                guidance, event = await self.shortfall_guidance(
                                    obligation.university_id
                                )
                                text += "\n" + guidance
                                events += (event,)
        else:
            assessment = await self.port.assess_message(message, actor)
            events = (ToolEvent(tool="assess_fraud_risk", status="OK"),)
            text = explain_assessment(assessment)
        return AgentResponse(
            run_id="pending",
            message=prefix + text,
            requested_action=intent,
            tool_events=events,
            resources=resources,
        )

    async def safe_handle(self, intent: Intent, message: str, actor: ActorContext) -> AgentResponse:
        try:
            return await self.handle(intent, message, actor)
        except ScopeDenied:
            raise
        except ServiceUnavailable:
            return AgentResponse(
                run_id="pending",
                requested_action=intent,
                message="Trusted service unavailable. No financial action was taken.",
                tool_events=(ToolEvent(tool="domain_read", status="UNAVAILABLE"),),
            )
