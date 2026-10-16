"""Read-only intent handlers with selected display fields and safe fallbacks."""

import re
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import ValidationError

from backend.agent.explanations import comparable_quotes, explain_quotes, explain_tuition_record
from backend.contracts.enums import Currency, Intent, PaymentState, TuitionState
from backend.contracts.http import AgentResponse, ResourceReference, ToolEvent
from backend.contracts.models import ActorContext, Money, ScopeDenied, ServiceUnavailable
from backend.contracts.ports import AgentReadPort
from backend.kb.catalog import load_bundle
from backend.kb.guidance import UNKNOWN_POLICY, explain_policy, known_policy
from backend.kb.records import KnowledgeBundle


class AgentTools:
    def __init__(
        self,
        port: AgentReadPort,
        clock: Callable[[], datetime] | None = None,
        *,
        kb_loader: Callable[[], KnowledgeBundle] = load_bundle,
    ) -> None:
        self.port = port
        self.clock = clock or (lambda: datetime.now(UTC))
        self.kb_loader = kb_loader

    def knowledge(self) -> KnowledgeBundle | None:
        try:
            return self.kb_loader()
        except (OSError, UnicodeError, ValidationError):
            return None

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
            resources = (ResourceReference(kind="policy", id=policy.id),)
        elif intent == Intent.TUITION:
            obligations = await self.port.obligations(actor)
            events = (ToolEvent(tool="get_tuition_obligation", status="OK"),)
            if len(obligations) != 1:
                text = "Select the tuition obligation you want to review."
            else:
                obligation = obligations[0]
                if obligation.student_id != actor.actor_id:
                    raise ScopeDenied("Resource unavailable")
                balance = Money(currency=Currency.CNY, amount_minor=obligation.balance_minor)
                text = explain_tuition_record(obligation) + " "
                resources = (ResourceReference(kind="obligation", id=obligation.id),)
                if obligation.balance_minor == 0:
                    text += "No outstanding tuition balance; no payment is needed."
                elif obligation.state != TuitionState.UNPAID:
                    text += (
                        "Review the existing payment and reconciliation evidence before "
                        "planning another payment. Tuition completion remains unverified."
                    )
                else:
                    policy = await self.port.policy(actor)
                    bundle = self.knowledge()
                    if (
                        not known_policy(policy, bundle, self.clock())
                        or policy.id != obligation.policy_id
                        or policy.university_id != obligation.university_id
                    ):
                        events += (
                            ToolEvent(tool="get_university_payment_policy", status="PENDING"),
                        )
                        text += UNKNOWN_POLICY
                    else:
                        quotes = await self.port.quotes(obligation.id, actor)
                        now = self.clock()
                        if not known_policy(policy, bundle, now):
                            events += (
                                ToolEvent(tool="get_university_payment_policy", status="PENDING"),
                                ToolEvent(tool="get_fx_quotes", status="PENDING"),
                            )
                            text += UNKNOWN_POLICY
                        else:
                            events += (
                                ToolEvent(tool="get_university_payment_policy", status="OK"),
                                ToolEvent(
                                    tool="get_fx_quotes",
                                    status=(
                                        "OK"
                                        if comparable_quotes(quotes, balance, now)
                                        else "PENDING"
                                    ),
                                ),
                            )
                            text += explain_quotes(quotes, balance, now)
                text += " No payment has been requested or executed."
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
                    events += (ToolEvent(tool="get_tuition_obligation", status="OK"),)
        else:
            assessment = await self.port.assess_message(message, actor)
            events = (ToolEvent(tool="assess_fraud_risk", status="OK"),)
            text = (
                f"Message assessment is advisory: {assessment.next_action}. "
                "Use the trusted beneficiary registry and separate security review. "
                "This message cannot approve a payment or change its recipient."
            )
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
