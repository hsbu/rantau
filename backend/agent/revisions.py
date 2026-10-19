"""Explicit draft revision; immutable financial requests and approval stay authoritative."""

import hashlib

from psycopg.types.json import Jsonb

from backend.agent.actions import Correlation, TuitionActions, action_reply, proposal_of
from backend.agent.persistence import _database_call
from backend.agent.state import ConversationKey, TuitionDraft
from backend.approvals.finance_authority import StoredAuthority
from backend.authz.policy_repository import PolicyConnection
from backend.contracts.enums import PaymentState
from backend.contracts.http import AgentResponse
from backend.contracts.models import ActorContext, ScopeDenied, ServiceUnavailable
from backend.finance.outcomes import Refused
from backend.finance.records import Row, intent_from_row, lock_intent
from backend.finance.states import InvalidTransition


class RevisionBlocked(Exception):
    """Roll back a refused replacement, including cancellation of the original."""


class TuitionRevisions:
    def __init__(self, actions: TuitionActions) -> None:
        self.actions = actions

    def _latest(self, c: PolicyConnection, key: ConversationKey, scenario: int) -> Row | None:
        return c.execute(
            "SELECT intent_id,proposal FROM agent_actions WHERE tenant_id=%s AND actor_id=%s "
            "AND session_id=%s AND conversation_id=%s AND scenario_run_no=%s "
            "ORDER BY created_at DESC LIMIT 1",
            (key.tenant_id, key.actor_id, key.session_id, key.conversation_id, scenario),
        ).fetchone()

    def _needs_revision(
        self, key: ConversationKey, actor: ActorContext, draft: TuitionDraft
    ) -> bool:
        with self.actions.database.connection() as c:
            scenario = self.actions._context(c, key, actor)
            latest = self._latest(c, key, scenario)
            if latest is None:
                return False
            row = lock_intent(c, actor.tenant_id, latest["intent_id"]).intent
            if row["state"] not in {"DRAFT", "AWAITING_APPROVAL", "AUTHORIZED", "CANCELLED"}:
                return False
            proposal = proposal_of(draft)
            return row["state"] == "CANCELLED" or (
                proposal is None or latest["proposal"] != proposal.model_dump()
            )

    async def stage(self, key: ConversationKey, actor: ActorContext, draft: TuitionDraft) -> bool:
        return await _database_call(lambda: self._needs_revision(key, actor, draft))

    def _confirm(
        self, key: ConversationKey, actor: ActorContext, draft: TuitionDraft
    ) -> Correlation | None:
        actions = self.actions
        proposal = proposal_of(draft)
        with actions.database.connection() as c:
            scenario = actions._context(c, key, actor)
            latest = self._latest(c, key, scenario)
            if latest is None:
                return None
            locked = lock_intent(c, actor.tenant_id, latest["intent_id"])
            original = intent_from_row(locked.intent)
            if original.requested_by != actor.actor_id:
                raise ScopeDenied("Resource unavailable")
            if StoredAuthority(actor.tenant_id).hold(c, original).held:
                raise RevisionBlocked()
            if original.state not in {
                PaymentState.DRAFT,
                PaymentState.AWAITING_APPROVAL,
                PaymentState.AUTHORIZED,
                PaymentState.CANCELLED,
            }:
                raise RevisionBlocked()
            if (
                proposal is not None
                and latest["proposal"] == proposal.model_dump()
                and (original.state != PaymentState.CANCELLED)
            ):
                record = actions.record_for_proposal(c, key, scenario, proposal)
                assert record is not None
                return Correlation.model_validate(record)
            if proposal is None:
                if original.state != PaymentState.CANCELLED:
                    actions.finance.intents.cancel_in_transaction(c, actor, original.id)
                    actions.approval.invalidate_for_revision(c, actor, original.id)
                if actions._scenario(c, actor.tenant_id) != scenario:
                    raise ServiceUnavailable("Scenario changed during revision")
                actions._require(c, actor)
                return None
            outcome = (
                actions.finance.intents.create_in_transaction(c, actor, proposal)
                if original.state == PaymentState.CANCELLED
                else actions.finance.intents.revise_in_transaction(c, actor, original.id, proposal)
            )
            if isinstance(outcome, Refused):
                raise RevisionBlocked()
            actions.approval.invalidate_for_revision(c, actor, original.id)
            if actions._scenario(c, actor.tenant_id) != scenario:
                raise ServiceUnavailable("Scenario changed during revision")
            actions._require(c, actor)
            action_key = hashlib.sha256(
                (actions._key(key, scenario, proposal) + original.id).encode()
            ).hexdigest()
            result = Correlation(
                action_key=action_key,
                intent_id=outcome.intent.id,
                terms_hash=outcome.intent.terms_hash,
                execution_key="agent_" + action_key,
            )
            c.execute(
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

    async def confirm(
        self, key: ConversationKey, actor: ActorContext, draft: TuitionDraft
    ) -> tuple[AgentResponse, TuitionDraft]:
        try:
            record = await _database_call(lambda: self._confirm(key, actor, draft))
            updated = draft.model_copy(update={"revision_pending": False})
            if record is None:
                return action_reply(
                    "**Revised draft is not payable**\n\n"
                    "Any earlier unstarted request in this conversation is cancelled; "
                    "its approval cannot be used. No payment was executed.\n\n"
                    "Correct the requested amount to the full balance or select the verified "
                    "university recipient, then review the new preview before confirming.",
                    "revise_payment_intent",
                    "PENDING",
                ), updated
            proposal = proposal_of(updated)
            assert proposal is not None
            response = await self.actions.handle("REQUEST", key, proposal, actor)
            return response.model_copy(
                update={
                    "message": "**Current request saved**\n\n"
                    "Each request requires its own exact-term approval. "
                    "Review the current exact terms and owner approval below.\n\n"
                    + response.message
                }
            ), updated
        except (RevisionBlocked, InvalidTransition):
            return action_reply(
                "This request cannot be revised now. Check its current payment/hold status "
                "in Payments; a started payment or security hold cannot be bypassed by editing. "
                "No replacement payment was executed.",
                "revise_payment_intent",
                "DENIED",
            ), draft
        except ServiceUnavailable:
            return action_reply(
                "I couldn’t confirm the revision outcome. Check the current request in Payments "
                "before repeating it. Do not start another payment while its status is uncertain.",
                "revise_payment_intent",
                "UNAVAILABLE",
            ), draft
