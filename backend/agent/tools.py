"""Read-only intent handlers with selected display fields and safe fallbacks."""

import re
from collections.abc import Callable
from datetime import UTC, datetime

from backend.contracts.enums import Intent, PaymentState, TuitionState
from backend.contracts.http import AgentResponse, ResourceReference, ToolEvent
from backend.contracts.models import ActorContext, ScopeDenied, ServiceUnavailable
from backend.contracts.ports import AgentReadPort


class AgentTools:
    def __init__(self, port: AgentReadPort, clock: Callable[[], datetime] | None = None) -> None:
        self.port = port
        self.clock = clock or (lambda: datetime.now(UTC))

    async def handle(self, intent: Intent, message: str, actor: ActorContext) -> AgentResponse:
        prefix = "Simulated Rantau guidance. "
        events: tuple[ToolEvent, ...] = ()
        resources: tuple[ResourceReference, ...] = ()
        if intent == Intent.ASK_POLICY:
            policy = await self.port.policy(actor)
            events = (ToolEvent(tool="get_university_payment_policy", status="OK"),)
            if not policy.usable_at(self.clock()):
                text = (
                    "University policy is unknown or expired. Verify it before planning a payment."
                )
            else:
                # Use only known structured values, never execute free-form KB text.
                text = (
                    f"The fictional policy {policy.version} has "
                    f"{len(policy.required_references)} required reference fields. "
                    f"Its synthetic posting window is {policy.posting_window_hours} hours. "
                    "These are fictional demo rules, not official university terms."
                )
            resources = (ResourceReference(kind="policy", id=policy.id),)
        elif intent == Intent.TUITION:
            obligations = await self.port.obligations(actor)
            events = (ToolEvent(tool="get_tuition_obligation", status="OK"),)
            if len(obligations) != 1:
                text = "Select the tuition obligation you want to review."
            else:
                obligation = obligations[0]
                text = (
                    f"Verified tuition balance: CNY {obligation.balance_minor // 100:,}."
                    f"{obligation.balance_minor % 100:02d}. "
                    "Next, review an eligible funding account, verified beneficiary and quote. "
                    "No payment has been requested or executed."
                )
                resources = (ResourceReference(kind="obligation", id=obligation.id),)
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
