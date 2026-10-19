"""Explicit tuition commands; durable correlation never substitutes for B/C authorization."""

import hashlib
import json
from typing import Literal

from psycopg.types.json import Jsonb

from backend.agent.persistence import _database_call, _lock_id, _Storage
from backend.agent.state import ConversationKey, TuitionDraft
from backend.approvals.finance_authority import StoredAuthority
from backend.approvals.service import ApprovalConflict, ApprovalService
from backend.approvals.store import database_time, terms_of
from backend.authz.policy_repository import PolicyConnection
from backend.contracts.enums import ApprovalState, Intent, PaymentState
from backend.contracts.http import AgentResponse, ResourceReference, ToolEvent
from backend.contracts.models import (
    ActorContext,
    Contract,
    IntentProposal,
    PaymentIntent,
    ScopeDenied,
    ServiceUnavailable,
)
from backend.finance.outcomes import Refused
from backend.finance.records import Row, intent_from_row, lock_intent
from backend.finance.wiring import FinanceServices

Command = Literal["REQUEST", "CONTINUE"]


def action_command(message: str) -> Command | None:
    text = message.strip().casefold().rstrip(".!?")
    if text in {"confirm tuition", "request tuition approval", "request approval"}:
        return "REQUEST"
    if text in {"check", "continue", "check approval", "continue tuition"}:
        return "CONTINUE"
    return None


def proposal_of(draft: TuitionDraft) -> IntentProposal | None:
    if draft.awaiting or not all(
        (draft.obligation_id, draft.source_account_id, draft.beneficiary_id, draft.quote_id)
    ):
        return None
    assert draft.source_account_id and draft.beneficiary_id and draft.quote_id
    return IntentProposal(
        obligation_id=draft.obligation_id,
        source_account_id=draft.source_account_id,
        beneficiary_id=draft.beneficiary_id,
        quote_id=draft.quote_id,
        purpose="TUITION",
    )


def action_reply(
    text: str, tool: str, status: str = "PENDING", payment_id: str | None = None
) -> AgentResponse:
    event = ToolEvent.model_validate({"tool": tool, "status": status})
    return AgentResponse(
        run_id="pending",
        requested_action=Intent.TUITION,
        message=text,
        tool_events=(event,),
        resources=(ResourceReference(kind="payment", id=payment_id),) if payment_id else (),
    )


def payment_status_message(state: PaymentState) -> str:
    if state == PaymentState.OUTCOME_UNKNOWN:
        return (
            "**Payment outcome is uncertain**\n\n"
            "The provider has not confirmed the result; tuition is not confirmed paid. "
            "Check the original payment in Payments before any retry. "
            "Do not create another payment while this outcome is unknown."
        )
    if state == PaymentState.FAILED:
        return (
            "**Payment failed**\n\n"
            "The provider reports this attempt failed; tuition is not confirmed paid. "
            "Review the original request and current account balance in Payments "
            "before planning another payment. Continuing here only rechecks this attempt."
        )
    return (
        f"Payment status: {state.value}; tuition is not "
        "confirmed paid by provider status. Verify university posting."
    )


class Correlation(Contract):
    action_key: str
    intent_id: str
    terms_hash: str
    execution_key: str


class ActionTermsChanged(Exception):
    """An existing confirmed request must be explicitly cancelled/revised before replacement."""


class TuitionActions(_Storage):
    def __init__(self, finance: FinanceServices, approval: ApprovalService) -> None:
        super().__init__(finance.database, finance.auth)
        self.finance, self.approval = finance, approval

    def _context(
        self, connection: PolicyConnection, key: ConversationKey, actor: ActorContext
    ) -> int:
        if (key.tenant_id, key.actor_id, key.session_id) != (
            actor.tenant_id,
            actor.actor_id,
            actor.session_id,
        ):
            raise ScopeDenied("Resource unavailable")
        self._require(connection, actor)
        # Do not lock demo_state before C locks the funding account: reset takes
        # account locks first. Revalidate and lock the scenario after creation.
        row = connection.execute(
            "SELECT run_no FROM demo_state WHERE tenant_id=%s", (actor.tenant_id,)
        ).fetchone()
        return int(row["run_no"]) if row else 0

    @staticmethod
    def _key(key: ConversationKey, scenario: int, proposal: IntentProposal) -> str:
        return hashlib.sha256(
            json.dumps([key.model_dump(), scenario, proposal.model_dump()], sort_keys=True).encode()
        ).hexdigest()

    @staticmethod
    def record_for_proposal(
        connection: PolicyConnection, key: ConversationKey, scenario: int, proposal: IntentProposal
    ) -> Row | None:
        return connection.execute(
            "SELECT action_key,intent_id,terms_hash,execution_key FROM agent_actions "
            "WHERE tenant_id=%s AND actor_id=%s AND session_id=%s AND conversation_id=%s "
            "AND scenario_run_no=%s AND proposal=%s ORDER BY created_at DESC LIMIT 1",
            (
                key.tenant_id,
                key.actor_id,
                key.session_id,
                key.conversation_id,
                scenario,
                Jsonb(proposal.model_dump()),
            ),
        ).fetchone()

    def _prepare(
        self, key: ConversationKey, proposal: IntentProposal, actor: ActorContext, *, create: bool
    ) -> Correlation | Refused | None:
        with self.database.connection() as connection:
            scenario = self._context(connection, key, actor)
            action_key = self._key(key, scenario, proposal)
            connection.execute(
                "SELECT pg_advisory_xact_lock(%s)", (_lock_id("agent-action", (action_key,)),)
            )
            row = self.record_for_proposal(connection, key, scenario, proposal)
            if row:
                self._require(connection, actor)
                return Correlation.model_validate(row)
            if not create:
                return None
            # One active confirmed request per conversation. A changed preview never
            # silently replaces terms or reuses the previous owner's approval.
            previous = connection.execute(
                "SELECT a.intent_id FROM agent_actions a JOIN payment_intents i "
                "ON i.tenant_id=a.tenant_id AND i.alias=a.intent_id "
                "WHERE a.tenant_id=%s AND a.actor_id=%s AND a.session_id=%s "
                "AND a.conversation_id=%s AND a.scenario_run_no=%s "
                "AND i.state NOT IN ('CANCELLED','FAILED','REJECTED','EXPIRED')",
                (key.tenant_id, key.actor_id, key.session_id, key.conversation_id, scenario),
            ).fetchone()
            if previous:
                raise ActionTermsChanged()
            outcome = self.finance.intents.create_in_transaction(connection, actor, proposal)
            if isinstance(outcome, Refused):
                return outcome
            if self._scenario(connection, actor.tenant_id) != scenario:
                raise ServiceUnavailable("Scenario changed during proposal creation")
            self._require(connection, actor)
            result = Correlation(
                action_key=action_key,
                intent_id=outcome.intent.id,
                terms_hash=outcome.intent.terms_hash,
                execution_key="agent_" + action_key,
            )
            connection.execute(
                "INSERT INTO agent_actions (action_key,tenant_id,actor_id,session_id,"
                "conversation_id,scenario_run_no,proposal,intent_id,terms_hash,execution_key) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    action_key,
                    key.tenant_id,
                    key.actor_id,
                    key.session_id,
                    key.conversation_id,
                    scenario,
                    Jsonb(proposal.model_dump()),
                    result.intent_id,
                    result.terms_hash,
                    result.execution_key,
                ),
            )
            return result

    def _current(self, actor: ActorContext, record: Correlation) -> tuple[PaymentIntent, str]:
        with self.database.connection() as connection:
            self._require(connection, actor)
            intent = intent_from_row(
                lock_intent(connection, actor.tenant_id, record.intent_id).intent
            )
            if intent.requested_by != actor.actor_id or intent.terms_hash != record.terms_hash:
                raise ScopeDenied("Resource unavailable")
            authority = StoredAuthority(actor.tenant_id)
            if authority.hold(connection, intent).held:
                return intent, "HELD"
            approval = authority.approval(connection, intent)
            now = database_time(connection)
            if intent.quote_expiry <= now:
                return intent, "EXPIRED"
            if approval is not None:
                if terms_of(approval) != terms_of(intent):
                    return intent, "INVALID"
                if approval.expires_at <= now:
                    return intent, "EXPIRED"
                return intent, approval.state.value
            return intent, "NONE"

    async def handle(
        self, command: Command, key: ConversationKey, proposal: IntentProposal, actor: ActorContext
    ) -> AgentResponse:
        try:
            record = await _database_call(
                lambda: self._prepare(key, proposal, actor, create=command == "REQUEST")
            )
            if isinstance(record, Refused):
                return action_reply(
                    "The protected backend refused this proposal. No debit occurred.",
                    "create_payment_intent",
                    "DENIED",
                )
            if record is None:
                return action_reply(
                    "No confirmed request matches this preview. Cancel or revise any earlier "
                    "request in Payments before using changed terms; existing approval does "
                    "not cover them. If you have not saved a request yet, review this preview "
                    "and say 'confirm tuition'.",
                    "get_approval_status",
                )
            if command == "REQUEST":
                intent, approval = await _database_call(lambda: self._current(actor, record))
                if intent.state == PaymentState.AWAITING_APPROVAL and approval in {
                    "NONE",
                    "PENDING",
                }:
                    await _database_call(lambda: self.approval.request(actor, record.intent_id))
                    own_funding = intent.funding_owner_id == actor.actor_id
                    waiting = (
                        "**Waiting for your approval**\n\n"
                        "Your request is saved using your own account. You need to approve "
                        "these exact terms through your authenticated account. "
                        if own_funding
                        else "**Waiting for funding-owner approval**\n\n"
                        "Your request is saved. The funding owner needs to review "
                        "these exact terms in their approval workspace. "
                    )
                    return action_reply(
                        waiting + "No payment was executed.\n\n"
                        "After approval, say `continue tuition` to proceed with this payment.",
                        "request_approval",
                    )
                if intent.state == PaymentState.DRAFT and approval == "NONE":
                    return action_reply(
                        "**Payment request saved**\n\n"
                        "Say `continue tuition` when you’re ready to proceed "
                        "with these exact terms. "
                        "Current permissions and payment checks still apply. No debit occurred.",
                        "create_payment_intent",
                        "OK",
                    )
                return action_reply(
                    "This payment request is already saved. No new execution was requested.\n\n"
                    "Review its status in Payments. Say `continue tuition` only when "
                    "you want to proceed with the saved payment.",
                    "create_payment_intent",
                    "OK",
                )
            return await self._continue(actor, record)
        except ActionTermsChanged:
            return action_reply(
                "This conversation already has a confirmed request. Cancel or revise it in "
                "Payments before confirming changed terms. Existing approval cannot authorize "
                "this changed preview. No new request or debit occurred.",
                "create_payment_intent",
                "DENIED",
            )
        except ApprovalConflict:
            return action_reply(
                "Approval is no longer reviewable for these terms. Refresh the "
                "proposal and obtain current owner approval. No execution requested.",
                "request_approval",
                "DENIED",
            )
        except ServiceUnavailable:
            return action_reply(
                "I couldn’t confirm the outcome.\n\n"
                "Check the original request in Payments before any retry. "
                "Do not create another payment request while its outcome is uncertain.",
                "get_approval_status",
                "UNAVAILABLE",
            )

    async def _continue(self, actor: ActorContext, record: Correlation) -> AgentResponse:
        # Recover committed submissions before considering another executor invocation.
        existing = await _database_call(
            lambda: self.finance.reads.payment_for_intent(actor, record.intent_id)
        )
        if existing is not None:
            await _database_call(
                lambda: self.finance.transfers.settle(actor.tenant_id, existing.payment_id)
            )
            result = await _database_call(
                lambda: self.finance.reads.payment_result(actor, existing.payment_id)
            )
            return action_reply(
                payment_status_message(result.transfer_status),
                "get_payment_status",
                "OK",
                result.payment_id,
            )
        intent, approval = await _database_call(lambda: self._current(actor, record))
        if approval in {
            "HELD",
            "EXPIRED",
            "INVALID",
            "REJECTED",
            "CONSUMED",
            "REVOKED",
            "INVALIDATED_BY_CHANGE",
        } or intent.state in {
            PaymentState.ON_HOLD,
            PaymentState.REJECTED,
            PaymentState.CANCELLED,
            PaymentState.EXPIRED,
            PaymentState.FAILED,
            PaymentState.PROCESSING,
            PaymentState.DELIVERED,
        }:
            stopped_state = (
                intent.state.value
                if intent.state
                in {
                    PaymentState.ON_HOLD,
                    PaymentState.REJECTED,
                    PaymentState.CANCELLED,
                    PaymentState.EXPIRED,
                    PaymentState.FAILED,
                    PaymentState.PROCESSING,
                    PaymentState.DELIVERED,
                }
                else approval
            )
            return action_reply(
                f"Execution stopped: {stopped_state}. "
                "Review the current request; no new debit was requested.",
                "get_approval_status",
                "DENIED",
            )
        if intent.state in {PaymentState.AWAITING_APPROVAL, PaymentState.AUTHORIZED} and (
            approval != ApprovalState.APPROVED.value
        ):
            return action_reply(
                "**Waiting for funding-owner approval**\n\n"
                "There is no current approval for these exact terms. The funding owner "
                "must approve in their own workspace; a message in Chat cannot do that. "
                "No payment was executed.",
                "get_approval_status",
            )
        outcome = await _database_call(
            lambda: self.finance.executor.execute(
                actor, record.intent_id, record.execution_key, record.terms_hash
            )
        )
        if isinstance(outcome, Refused):
            return action_reply(
                "The protected backend blocked execution after rechecking current "
                "authority, terms, holds and limits. No new debit occurred.",
                "execute_payment",
                "DENIED",
            )
        return action_reply(
            payment_status_message(outcome.transfer_state),
            "execute_payment",
            "OK",
            outcome.payment_id,
        )
