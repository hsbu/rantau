"""Read-only tuition drafts from current scoped services; never creates or executes payment."""

from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal

from backend.agent.explanations import (
    comparable_quotes,
    display_time,
    explain_cost_difference,
    explain_quotes,
    explain_selected_quote,
    explain_tuition_record,
    format_money,
    route_label,
)
from backend.agent.openrouter_classifier import redact_for_model
from backend.agent.state import TuitionDraft, TuitionInput
from backend.contracts.enums import Currency, Intent, TuitionState
from backend.contracts.http import AgentResponse, ResourceReference, ToolEvent
from backend.contracts.models import ActorContext, IntentProposal, Money, ScopeDenied
from backend.contracts.ports import AgentReadPort
from backend.kb.guidance import UNKNOWN_POLICY, known_policy
from backend.kb.records import KnowledgeBundle


def select_option(
    option: int | None,
    selected: str | None,
    advertised: tuple[str, ...],
    current: tuple[str, ...],
    *,
    automatic: bool,
) -> str | None:
    if option is not None:
        choices = advertised or current
        if option <= len(choices) and choices[option - 1] in current:
            return choices[option - 1]
        return None
    if selected is not None:
        return selected if selected in current else None
    return current[0] if len(current) == 1 and automatic else None


class TuitionPlanner:
    def __init__(
        self,
        port: AgentReadPort,
        clock: Callable[[], datetime],
        knowledge: Callable[[], KnowledgeBundle | None],
        beneficiaries: Mapping[str, str] | None,
    ) -> None:
        self.port = port
        self.clock = clock
        self.knowledge = knowledge
        # Only trusted server wiring supplies university-to-registry-ID bindings.
        self.beneficiaries = dict(beneficiaries or {})

    async def plan(
        self, inputs: TuitionInput, draft: TuitionDraft, actor: ActorContext
    ) -> tuple[AgentResponse, TuitionDraft]:
        if inputs.restart and not inputs.information_only:
            draft = TuitionDraft()
        events: list[ToolEvent] = []
        resources: tuple[ResourceReference, ...] = ()

        def reply(text: str, updated: TuitionDraft) -> tuple[AgentResponse, TuitionDraft]:
            trace = tuple(events)
            if updated.awaiting is not None and not inputs.information_only:
                trace += (ToolEvent(tool="clarify_tuition", status="PENDING"),)
            return (
                AgentResponse(
                    run_id="pending",
                    requested_action=Intent.TUITION,
                    message=text,
                    tool_events=trace,
                    resources=resources,
                ),
                updated,
            )

        obligations = await self.port.obligations(actor)
        events.append(ToolEvent(tool="get_tuition_obligation", status="OK"))
        if any(item.student_id != actor.actor_id for item in obligations):
            raise ScopeDenied("Resource unavailable")
        if not obligations:
            return reply("No tuition obligation is available in your scope.", TuitionDraft())
        if len(obligations) > 100:
            return reply("Narrow the tuition search before continuing.", TuitionDraft())
        ids = tuple(item.id for item in obligations)
        if len(set(ids)) != len(ids):
            return reply("Tuition records are ambiguous; refresh the records.", TuitionDraft())
        selected = select_option(
            inputs.obligation_option,
            draft.obligation_id,
            draft.obligation_options,
            ids,
            automatic=draft.awaiting != "OBLIGATION",
        )
        if selected is None:
            choices = "\n\n".join(
                f"Obligation {index}: {explain_tuition_record(item)}"
                for index, item in enumerate(obligations, 1)
            )
            return reply(
                "Which tuition bill would you like to review?\n\n" + choices,
                draft.model_copy(update={"awaiting": "OBLIGATION", "obligation_options": ids}),
            )
        obligation = next(item for item in obligations if item.id == selected)
        if draft.obligation_id != selected:
            draft = TuitionDraft(obligation_id=selected, obligation_options=ids)
        resources = (ResourceReference(kind="obligation", id=selected),)
        summary = explain_tuition_record(obligation) + "\n\n"
        if inputs.information_only:
            return reply(summary.rstrip(), draft)
        if obligation.state == TuitionState.PAID:
            return reply(summary + "No outstanding tuition balance; no payment is needed.", draft)
        if obligation.state != TuitionState.UNPAID:
            return reply(
                summary
                + "Review the existing payment/reconciliation evidence before another payment.",
                draft.model_copy(update={"quote_id": None, "awaiting": None}),
            )
        policy = await self.port.policy(actor)
        bundle = self.knowledge()
        if (
            not known_policy(policy, bundle, self.clock())
            or policy.id != obligation.policy_id
            or policy.university_id != obligation.university_id
        ):
            events.append(ToolEvent(tool="get_university_payment_policy", status="PENDING"))
            return reply(summary + UNKNOWN_POLICY, draft.model_copy(update={"quote_id": None}))
        events.append(ToolEvent(tool="get_university_payment_policy", status="OK"))
        amount = draft.requested_amount_minor
        if inputs.full_balance:
            amount = None
        elif inputs.amount_cny is not None:
            amount = int(Decimal(inputs.amount_cny) * 100)
        draft = draft.model_copy(update={"requested_amount_minor": amount})
        if inputs.amount_unclear or (
            draft.awaiting == "AMOUNT" and not inputs.full_balance and inputs.amount_cny is None
        ):
            return reply(
                "What amount would you like to pay in CNY? You can also say `full balance`.",
                draft.model_copy(update={"awaiting": "AMOUNT", "quote_id": None}),
            )
        if amount is not None and amount != obligation.balance_minor:
            return reply(
                summary + "This payment needs to cover the full outstanding balance. "
                "Say `full balance`, or review the existing shortfall case in Payments.",
                draft.model_copy(update={"awaiting": "AMOUNT", "quote_id": None}),
            )
        permissions = tuple(
            item
            for item in await self.port.permissions(actor)
            if "TUITION" in item.permitted_purposes
        )
        events.append(ToolEvent(tool="get_account_permissions", status="OK"))
        if not permissions or len(permissions) > 100:
            return reply(summary + "No unambiguous tuition funding permission is available.", draft)
        funding_ids = tuple(item.account_id for item in permissions)
        if len(set(funding_ids)) != len(funding_ids):
            return reply(summary + "Funding records are ambiguous; refresh permissions.", draft)
        candidates = tuple(
            item.account_id
            for item in permissions
            if inputs.funding_owner is None
            or (item.owner_id == actor.actor_id) == (inputs.funding_owner == "SELF")
        )
        funding = select_option(
            inputs.funding_option,
            None if inputs.funding_owner else draft.source_account_id,
            draft.funding_options or funding_ids,
            candidates,
            automatic=draft.awaiting != "FUNDING" or inputs.funding_owner is not None,
        )
        if funding is None:
            labels = "\n".join(
                f"{index}. "
                + (
                    "your account."
                    if item.owner_id == actor.actor_id
                    else "another owner's account."
                )
                for index, item in enumerate(permissions, 1)
            )
            return reply(
                summary + "**Which funding account would you like to use?**\n\n" + labels,
                draft.model_copy(update={"awaiting": "FUNDING", "funding_options": funding_ids}),
            )
        permission = next(item for item in permissions if item.account_id == funding)
        draft = draft.model_copy(
            update={
                "source_account_id": funding,
                "funding_options": funding_ids,
                "quote_id": None if funding != draft.source_account_id else draft.quote_id,
            }
        )
        quotes = await self.port.quotes(obligation.id, actor)
        now = self.clock()
        if not known_policy(policy, bundle, now):
            events.append(ToolEvent(tool="get_university_payment_policy", status="PENDING"))
            return reply(summary + UNKNOWN_POLICY, draft.model_copy(update={"quote_id": None}))
        destination = Money(currency=Currency.CNY, amount_minor=obligation.balance_minor)
        current = comparable_quotes(quotes, destination, now)
        events.append(ToolEvent(tool="get_fx_quotes", status="OK" if current else "PENDING"))
        quote_ids = tuple(item.id for item in current)
        if not current or len(current) > 100:
            return reply(
                summary + explain_quotes(quotes, destination, now),
                draft.model_copy(update={"quote_id": None, "quote_options": ()}),
            )
        preference = inputs.route_preference or draft.route_preference
        if inputs.route_preference:
            draft = draft.model_copy(update={"quote_id": None, "awaiting": None})
        quote_id = select_option(
            inputs.quote_option,
            None if inputs.route_preference else draft.quote_id,
            draft.quote_options,
            quote_ids,
            automatic=draft.awaiting != "QUOTE",
        )
        if (
            quote_id is None
            and inputs.quote_option is None
            and draft.quote_id is None
            and draft.awaiting != "QUOTE"
        ):
            ranked = sorted(
                current,
                key=lambda item: (
                    (item.source_total_minor, item.estimated_delivery_at)
                    if preference == "LOWEST_COST"
                    else (item.estimated_delivery_at, item.source_total_minor)
                ),
            )
            best = ranked[0]
            if len(ranked) == 1 or (best.source_total_minor, best.estimated_delivery_at) != (
                ranked[1].source_total_minor,
                ranked[1].estimated_delivery_at,
            ):
                quote_id = best.id
        if quote_id is None:
            return reply(
                explain_quotes(quotes, destination, now) + "\n\nWhich route number would you like?",
                draft.model_copy(update={"awaiting": "QUOTE", "quote_options": quote_ids}),
            )
        draft = draft.model_copy(
            update={
                "quote_id": quote_id,
                "quote_options": quote_ids,
                "route_preference": preference,
                "awaiting": None,
            }
        )
        beneficiary_id = self.beneficiaries.get(obligation.university_id)
        if beneficiary_id is None:
            events.append(ToolEvent(tool="get_trusted_beneficiary", status="UNAVAILABLE"))
            return reply(
                summary
                + explain_quotes(quotes, destination, now)
                + "\n\nI can’t verify the university recipient yet. "
                "Reviewing this preview does not request or execute a payment.",
                draft,
            )
        beneficiary = await self.port.beneficiary(beneficiary_id, actor)
        if (
            beneficiary.id != beneficiary_id
            or beneficiary.owner_id != obligation.university_id
            or not beneficiary.verified
            or not beneficiary.fingerprint.strip()
        ):
            events.append(ToolEvent(tool="get_trusted_beneficiary", status="DENIED"))
            return reply(
                summary + "The payee cannot be verified; no intent preview is available.",
                draft.model_copy(update={"quote_id": None}),
            )
        quote = next(item for item in current if item.id == quote_id)
        now = self.clock()
        if quote.expires_at <= now or not known_policy(policy, bundle, now):
            events.append(ToolEvent(tool="build_tuition_preview", status="PENDING"))
            return reply(
                "The quote or policy expired. Refresh the preview before continuing.",
                draft.model_copy(update={"quote_id": None}),
            )
        # Preserve proposal validation without exposing internal identifiers in the reply.
        IntentProposal(
            obligation_id=obligation.id,
            source_account_id=funding,
            beneficiary_id=beneficiary.id,
            quote_id=quote.id,
            purpose="TUITION",
        )
        events.append(ToolEvent(tool="get_trusted_beneficiary", status="OK"))
        events.append(ToolEvent(tool="build_tuition_preview", status="OK"))
        draft = draft.model_copy(update={"beneficiary_id": beneficiary.id})
        approval = (
            (
                "You will need to approve these exact terms before payment."
                if permission.owner_id == actor.actor_id
                else "The funding owner will need to approve these exact terms before payment."
            )
            if permission.approval_required
            else "Your funding permission will be checked again before payment."
        )
        funding_label = (
            "your account" if permission.owner_id == actor.actor_id else "another owner's account"
        )
        payee = redact_for_model(beneficiary.masked_display[:160]).replace(
            "Fictional university", "University tuition account"
        )
        alternatives = [
            f"{index}. {route_label(other, index)}: "
            f"{format_money(Money(currency=Currency.IDR, amount_minor=other.source_total_minor))} "
            f"total; fee: "
            f"{format_money(Money(currency=Currency.IDR, amount_minor=other.fee_minor))}.\n"
            f"Receives the same {format_money(destination)}; "
            f"estimated arrival {display_time(other.estimated_delivery_at)}."
            for index, other in enumerate(current, 1)
            if other.id != quote.id
        ]
        other_routes = "\n\n**Other routes**\n\n" + "\n".join(alternatives) if alternatives else ""
        return reply(
            summary
            + explain_selected_quote(quote, current.index(quote) + 1)
            + explain_cost_difference(quote, current)
            + other_routes
            + f"\n\nFunding: {funding_label}.\nRecipient: {payee}.\n\n"
            + approval
            + " Reviewing this preview does not request or execute a payment.",
            draft,
        )
