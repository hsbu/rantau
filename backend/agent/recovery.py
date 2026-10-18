"""Scoped payment linkage and recovery selection; no payment execution capability."""

import re
from dataclasses import dataclass

from backend.agent.explanations import explain_tuition_record, format_money, utc_time
from backend.agent.persistence import _database_call, _Storage
from backend.agent.state import RecoveryDraft
from backend.authz.policy_repository import PolicyConnection
from backend.contracts.enums import CaseState, Intent, PaymentState, TuitionState
from backend.contracts.http import AgentResponse, ResourceReference, ToolEvent
from backend.contracts.models import (
    ActorContext,
    CaseSubmission,
    Money,
    PaymentResult,
    ScopeDenied,
    ServiceUnavailable,
    TuitionObligationDetail,
)
from backend.finance.records import Row, lock_intent
from backend.finance.simclock import sim_now
from backend.finance.wiring import FinanceServices
from backend.kb.research import OfficialSourceLookup, explain_research, research_event_status
from backend.university.obligations import read_obligation


@dataclass(frozen=True)
class RecoverySnapshot:
    payment: PaymentResult
    obligation: TuitionObligationDetail
    case_id: str | None
    case_state: CaseState | None
    linked_posting: bool
    scenario: int
    evidence_missing: tuple[str, ...] = ()


def recovery_command(message: str) -> str | None:
    text = message.strip().casefold().rstrip(".!?")
    return {"submit recovery": "SUBMIT", "check recovery": "CHECK"}.get(text)


def payment_selection_command(message: str) -> tuple[str, int | None] | None:
    text = message.strip().casefold().rstrip(".!?")
    if text in {"list payments", "list my payments", "show payments", "show my payments"}:
        return "LIST", None
    match = re.fullmatch(r"(?:(?:select |track |recover )?payment\s+)([0-9]{1,2})", text)
    return ("SELECT", int(match[1])) if match else None


class RecoveryWorkflow(_Storage):
    def __init__(
        self, finance: FinanceServices, *, research: OfficialSourceLookup | None = None
    ) -> None:
        super().__init__(finance.database, finance.auth)
        self.finance = finance
        self.research = research

    def _choices(self, actor: ActorContext) -> tuple[RecoverySnapshot, ...]:
        with self.database.connection() as c:
            self._require(c, actor)
            scenario = self._scenario(c, actor.tenant_id)
        intents = self.finance.reads.intent_list(actor)
        if len(intents) > 100:
            raise ServiceUnavailable("Narrow the payment search in Payments")
        choices: list[RecoverySnapshot] = []
        for item in intents:
            if item.purpose != "TUITION" or item.obligation_id is None:
                continue
            payment = self.finance.reads.payment_for_intent(actor, item.id)
            if payment is None:
                continue
            try:
                snapshot = self.snapshot(actor, payment.payment_id)
            except ScopeDenied:
                # C may expose a funding-owner view; recovery requires this student's link.
                continue
            if snapshot.scenario != scenario:
                raise ScopeDenied("Resource unavailable")
            choices.append(snapshot)
            if len(choices) == 10:
                break
        with self.database.connection() as c:
            self._require(c, actor)
            if self._scenario(c, actor.tenant_id) != scenario:
                raise ScopeDenied("Resource unavailable")
        return tuple(choices)

    async def list_payments(
        self, actor: ActorContext, intent: Intent
    ) -> tuple[AgentResponse, RecoveryDraft]:
        choices = await _database_call(lambda: self._choices(actor))
        lines = [
            "Up to 10 eligible tuition payments in your current scope. Listing makes no changes."
        ]
        for index, item in enumerate(choices, 1):
            amount = format_money(
                Money(
                    currency=item.obligation.currency, amount_minor=item.obligation.amount_due_minor
                )
            )
            lines.append(
                f"Payment {index}: tuition expected {amount}; provider "
                f"{item.payment.transfer_status.value}; university {item.obligation.state.value}; "
                f"tuition due {utc_time(item.obligation.due_at)}."
            )
        lines.append(
            "Say 'select payment 1' (or another listed number) to inspect its linked records. "
            "Selection does not submit a case or execute a payment."
            if choices
            else "No eligible tuition payment was found. Review the Payments workspace."
        )
        draft = RecoveryDraft(payment_options=tuple(x.payment.payment_id for x in choices))
        return AgentResponse(
            run_id="pending",
            requested_action=intent,
            message="\n".join(lines),
            tool_events=(ToolEvent(tool="list_student_payments", status="OK"),),
        ), draft

    async def select_payment(
        self,
        command: tuple[str, int | None],
        draft: RecoveryDraft,
        actor: ActorContext,
        intent: Intent,
    ) -> tuple[AgentResponse, RecoveryDraft]:
        if command[0] == "LIST":
            return await self.list_payments(actor, intent)
        index = command[1]
        if index is None or not 1 <= index <= len(draft.payment_options):
            return self.reply(
                "Select an advertised payment number, or say 'list payments' to refresh choices. "
                "No case or payment was submitted.",
                intent,
            ), draft
        payment_id = draft.payment_options[index - 1]
        snapshot = await _database_call(lambda: self.snapshot(actor, payment_id))
        response = await self.describe_with_guidance(actor, snapshot, intent)
        return response.model_copy(
            update={
                "tool_events": (
                    ToolEvent(tool="select_student_payment", status="OK", resource_id=payment_id),
                )
                + response.tool_events,
            }
        ), RecoveryDraft(
            payment_id=payment_id,
            obligation_id=snapshot.obligation.id,
            case_id=snapshot.case_id,
            payment_options=draft.payment_options,
        )

    def _link(self, connection: PolicyConnection, actor: ActorContext, payment_id: str) -> Row:
        self._require(connection, actor)
        row = connection.execute(
            "SELECT t.intent_alias,t.obligation_alias,i.requested_by,o.student_id, "
            "i.obligation_alias AS intent_obligation FROM transfers t "
            "JOIN payment_intents i ON i.tenant_id=t.tenant_id AND i.alias=t.intent_alias "
            "JOIN tuition_obligations o ON o.tenant_id=t.tenant_id AND o.alias=t.obligation_alias "
            "WHERE t.tenant_id=%s AND t.alias=%s",
            (actor.tenant_id, payment_id),
        ).fetchone()
        if (
            row is None
            or row["student_id"] != actor.actor_id
            or (
                row["requested_by"] != actor.actor_id
                or row["intent_obligation"] != row["obligation_alias"]
            )
        ):
            raise ScopeDenied("Resource unavailable")
        return row

    def snapshot(self, actor: ActorContext, payment_id: str) -> RecoverySnapshot:
        with self.database.connection() as c:
            row = self._link(c, actor, payment_id)
            scenario = self._scenario(c, actor.tenant_id)
            case = c.execute(
                "SELECT alias,state,evidence_missing FROM reconciliation_cases WHERE tenant_id=%s "
                "AND transfer_alias=%s ORDER BY created_at DESC,alias DESC LIMIT 1",
                (actor.tenant_id, payment_id),
            ).fetchone()
            posted = c.execute(
                "SELECT 1 FROM university_postings WHERE tenant_id=%s AND transfer_alias=%s "
                "AND obligation_alias=%s AND posted_minor>0 LIMIT 1",
                (actor.tenant_id, payment_id, row["obligation_alias"]),
            ).fetchone()
        payment = self.finance.reads.payment_result(actor, payment_id)
        obligation = self.finance.obligations.get(actor, row["obligation_alias"])
        with self.database.connection() as c:
            self._link(c, actor, payment_id)
            if self._scenario(c, actor.tenant_id) != scenario:
                raise ScopeDenied("Resource unavailable")
        return RecoverySnapshot(
            payment,
            obligation,
            case["alias"] if case else None,
            CaseState(case["state"]) if case else None,
            posted is not None,
            scenario,
            tuple(case["evidence_missing"]) if case else (),
        )

    async def investigate(
        self, message: str, draft: RecoveryDraft, actor: ActorContext, intent: Intent
    ) -> tuple[AgentResponse, RecoveryDraft]:
        references = set(re.findall(r"\btransfer_[A-Za-z0-9_-]+\b", message))
        if not references and draft.payment_id is None:
            return await self.list_payments(actor, intent)
        if len(references) > 1:
            return self.reply(
                "Select one payment reference, such as transfer_001, to check.", intent
            ), RecoveryDraft()
        payment_id = next(iter(references)) if references else draft.payment_id
        assert payment_id
        snapshot = await _database_call(lambda: self.snapshot(actor, payment_id))
        selected = RecoveryDraft(
            payment_id=payment_id,
            obligation_id=snapshot.obligation.id,
            case_id=snapshot.case_id,
            payment_options=draft.payment_options,
        )
        return await self.describe_with_guidance(actor, snapshot, intent), selected

    async def describe_with_guidance(
        self, actor: ActorContext, snapshot: RecoverySnapshot, intent: Intent = Intent.RECOVER
    ) -> AgentResponse:
        if (
            self.research is None
            or snapshot.obligation.university_id != "uni_cn_01"
            or snapshot.payment.transfer_status != PaymentState.DELIVERED
            or not 0 < snapshot.obligation.balance_minor < snapshot.obligation.amount_due_minor
        ):
            return self.describe(snapshot, intent)
        result = await self.research.lookup()
        # Retrieval grants no authority; refresh scope and records after the external wait.
        fresh = await _database_call(lambda: self.snapshot(actor, snapshot.payment.payment_id))
        response = self.describe(fresh, intent)
        return response.model_copy(
            update={
                "message": response.message
                + ("\n" + explain_research(result) if fresh.obligation.balance_minor else ""),
                "tool_events": response.tool_events
                + (
                    ToolEvent(
                        tool="lookup_shortfall_sources", status=research_event_status(result)
                    ),
                ),
            }
        )

    async def handle(
        self, command: str, draft: RecoveryDraft, actor: ActorContext
    ) -> tuple[AgentResponse, RecoveryDraft]:
        if draft.payment_id is None:
            return self.reply("Select a payment with 'recover transfer_…' first."), draft
        payment_id = draft.payment_id
        try:
            snapshot = await _database_call(lambda: self.snapshot(actor, payment_id))
            if snapshot.obligation.id != draft.obligation_id:
                raise ScopeDenied("Resource unavailable")
            events: tuple[ToolEvent, ...] = ()
            if command == "SUBMIT":
                created, submitted = await _database_call(lambda: self._submit(actor, snapshot))
                if created:
                    events += (ToolEvent(tool="create_reconciliation_case", status="OK"),)
                if submitted:
                    events += (ToolEvent(tool="submit_reconciliation_case", status="PENDING"),)
            else:
                # C owns provider status polling and automatic due-posting rules. Never
                # invoke the executor or the independent reconciliation review service.
                await _database_call(
                    lambda: self.finance.obligations.recheck(actor, snapshot.obligation.id)
                )
            current = await _database_call(lambda: self.snapshot(actor, payment_id))
            response = await self.describe_with_guidance(actor, current)
            if events:
                response = response.model_copy(
                    update={
                        "tool_events": response.tool_events
                        + tuple(
                            event.model_copy(update={"resource_id": current.case_id})
                            for event in events
                        )
                    }
                )
            selected = RecoveryDraft(
                payment_id=current.payment.payment_id,
                obligation_id=current.obligation.id,
                case_id=current.case_id,
            )
            return response, selected
        except ServiceUnavailable:
            return self.reply(
                "Recovery outcome is unavailable. Say 'check recovery' to reload the same "
                "payment/case before retrying. Do not make another payment."
            ).model_copy(
                update={
                    "tool_events": (
                        ToolEvent(tool="get_reconciliation_status", status="UNAVAILABLE"),
                    )
                }
            ), draft

    def _submit(self, actor: ActorContext, snapshot: RecoverySnapshot) -> tuple[bool, bool]:
        with self.database.connection() as c:
            row = self._link(c, actor, snapshot.payment.payment_id)
            locked = lock_intent(c, actor.tenant_id, row["intent_alias"])
            if self._scenario(c, actor.tenant_id) != snapshot.scenario:
                raise ScopeDenied("Resource unavailable")
            row = self._link(c, actor, snapshot.payment.payment_id)
            self._require(c, actor)
            if "reconciliation:submit" not in actor.scopes:
                raise ScopeDenied("Resource unavailable")
            transfer = c.execute(
                "SELECT state FROM transfers WHERE tenant_id=%s AND alias=%s FOR UPDATE",
                (actor.tenant_id, snapshot.payment.payment_id),
            ).fetchone()
            assert transfer is not None and locked.obligation is not None
            obligation = read_obligation(
                c, actor.tenant_id, locked.obligation, sim_now(c, actor.tenant_id)
            ).obligation
            case = c.execute(
                "SELECT alias,state FROM reconciliation_cases WHERE tenant_id=%s "
                "AND transfer_alias=%s ORDER BY created_at DESC,alias DESC LIMIT 1 FOR UPDATE",
                (actor.tenant_id, snapshot.payment.payment_id),
            ).fetchone()
            if transfer["state"] != PaymentState.DELIVERED.value or obligation.state not in {
                TuitionState.EXCEPTION,
                TuitionState.RECONCILIATION_PENDING,
                TuitionState.ESCALATED,
            }:
                return False, False
            if case and CaseState(case["state"]) not in {
                CaseState.OPEN,
                CaseState.READY,
                CaseState.EVIDENCE_REQUIRED,
                CaseState.NEEDS_INFO,
            }:
                return False, False
            created = case is None
            if case is None:
                opened = self.finance.cases.create_in_transaction(
                    c,
                    actor,
                    CaseSubmission(
                        payment_id=snapshot.payment.payment_id,
                        obligation_id=row["obligation_alias"],
                        evidence_ids=(),
                    ),
                )
                case_alias = opened.id
            else:
                case_alias = case["alias"]
            result = self.finance.cases.submit_in_transaction(c, actor, case_alias)
            self._require(c, actor)
            return created, result.state == CaseState.SUBMITTED

    @staticmethod
    def reply(text: str, intent: Intent = Intent.RECOVER) -> AgentResponse:
        return AgentResponse(
            run_id="pending", requested_action=intent, message="Simulated Rantau recovery. " + text
        )

    def describe(
        self, snapshot: RecoverySnapshot, intent: Intent = Intent.RECOVER
    ) -> AgentResponse:
        payment, obligation = snapshot.payment, snapshot.obligation
        text = f"Provider state: {payment.transfer_status.value}. "
        text += explain_tuition_record(obligation) + " "
        if obligation.state == TuitionState.PAID and snapshot.linked_posting:
            text += "PAID is verified by university postings linked to this payment and obligation."
        elif obligation.state == TuitionState.PAID:
            text += (
                "This obligation has been credited, but this payment has no linked university "
                "posting. Do not infer that this payment funded it; seek university review."
            )
        elif payment.transfer_status == PaymentState.OUTCOME_UNKNOWN:
            text += (
                "Provider outcome is unknown; check the original payment before any retry. "
                "No additional payment will be submitted."
            )
        elif payment.transfer_status != PaymentState.DELIVERED:
            text += (
                "Tuition is not confirmed paid. Recheck this original payment; do not pay again."
            )
        elif obligation.shortfall_minor:
            text += (
                "Tuition is not confirmed paid. "
                + (
                    "The synthetic policy permits separate top-up planning with fresh approval. "
                    if obligation.topup_permitted
                    else "The synthetic policy forbids a top-up; request university review. "
                )
                + "Recovery does not authorize or execute an additional payment."
            )
        else:
            text += "Tuition is not confirmed paid; do not make a duplicate payment. "
            if snapshot.case_state:
                text += f"Reconciliation state: {snapshot.case_state.value}. "
            elif obligation.state == TuitionState.EXCEPTION:
                text += (
                    "Say 'submit recovery' to collect backend receipt/reference/amount "
                    "evidence and submit a reconciliation case for independent review. "
                )
            else:
                text += "University posting is pending. "
                if obligation.posting_deadline_at:
                    deadline = obligation.posting_deadline_at.isoformat()
                    text += f"Simulated posting deadline: {deadline}. "
            text += "Say 'check recovery' to reload provider and university records."
        resources: tuple[ResourceReference, ...] = (
            ResourceReference(kind="payment", id=payment.payment_id),
            ResourceReference(kind="obligation", id=obligation.id),
        )
        if snapshot.case_state and f"Reconciliation state: {snapshot.case_state.value}" not in text:
            text += f" Reconciliation state: {snapshot.case_state.value}."
        if snapshot.evidence_missing:
            text += " Missing backend evidence: " + ", ".join(snapshot.evidence_missing) + "."
            text += " Wait for trusted records; pasted claims cannot replace verified evidence."
        if snapshot.case_id:
            resources += (ResourceReference(kind="case", id=snapshot.case_id),)
        events: tuple[ToolEvent, ...] = (
            ToolEvent(tool="get_payment_status", status="OK", resource_id=payment.payment_id),
            ToolEvent(tool="get_tuition_obligation", status="OK", resource_id=obligation.id),
        )
        if snapshot.case_id:
            events += (
                ToolEvent(
                    tool="get_reconciliation_status", status="OK", resource_id=snapshot.case_id
                ),
            )
        return AgentResponse(
            run_id="pending",
            requested_action=intent,
            message="Simulated Rantau recovery. " + text,
            tool_events=events,
            resources=resources,
        )
