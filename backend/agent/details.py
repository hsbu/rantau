"""Selected, current-session presentation reads; never invokes financial commands."""

import json

from pydantic import ValidationError

from backend.agent.actions import TuitionActions, proposal_of
from backend.agent.openrouter_classifier import redact_for_model
from backend.agent.persistence import MAX_STATE_BYTES, _database_call, _Storage
from backend.agent.state import ConversationKey, ConversationState
from backend.approvals.store import AuthorityStore, terms_of
from backend.authz.policy_repository import PolicyConnection
from backend.contracts.agent_details import (
    AgentActionSummary,
    AgentApprovalDetail,
    AgentDetailSnapshot,
    AgentPaymentDetail,
    AgentQuoteDetail,
    AgentRecoveryDetail,
    AgentTuitionDetail,
)
from backend.contracts.enums import ApprovalState, Intent, PaymentState
from backend.contracts.models import ActorContext, ScopeDenied, ServiceUnavailable
from backend.finance.clock import db_now
from backend.finance.quotes import quote_from_row
from backend.finance.records import Row, fetch, intent_from_row
from backend.finance.simclock import sim_now
from backend.finance.wiring import FinanceServices

EVIDENCE = {
    "RECEIPT": "Backend payment receipt",
    "PROVIDER_REFERENCE": "Verified provider reference",
    "AMOUNT": "Verified payment amount",
    "STUDENT_REFERENCE_CLAIM": "Verified student payment reference",
}


def label(value: str) -> str:
    return redact_for_model(value).replace("<", "").replace(">", "")[:120] or "Unavailable"


class AgentDetails(_Storage):
    def __init__(self, finance: FinanceServices) -> None:
        super().__init__(finance.database, finance.auth)
        self.finance = finance

    def _context(
        self, c: PolicyConnection, actor: ActorContext, conversation_id: str, run_id: str
    ) -> Row:
        self._require(c, actor)
        scenario = self._scenario(c, actor.tenant_id)
        row = c.execute(
            "SELECT d.state,d.revision,d.schema_version,d.scenario_run_no, "
            "r.metadata->>'requested_action' AS requested_action "
            "FROM agent_conversations d JOIN agent_runs r ON "
            "r.tenant_id=d.tenant_id AND r.actor_id=d.actor_id AND r.session_id=d.session_id "
            "AND r.conversation_id=d.conversation_id AND r.scenario_run_no=d.scenario_run_no "
            "WHERE d.tenant_id=%s AND d.actor_id=%s AND d.session_id=%s "
            "AND d.conversation_id=%s AND r.run_id=%s AND d.scenario_run_no=%s "
            "AND d.expires_at>clock_timestamp() AND r.created_at>=d.updated_at",
            (actor.tenant_id, actor.actor_id, actor.session_id, conversation_id, run_id, scenario),
        ).fetchone()
        if row is None:
            raise ScopeDenied("Resource unavailable")
        if row["schema_version"] != 1 or len(json.dumps(row["state"]).encode()) > MAX_STATE_BYTES:
            raise ServiceUnavailable("Conversation state unavailable")
        return row

    async def get(
        self, actor: ActorContext, conversation_id: str, run_id: str
    ) -> AgentDetailSnapshot:
        try:
            result = await _database_call(lambda: self._snapshot(actor, conversation_id, run_id))
            # A second transaction observes revocation/expiry or a superseding turn.
            await _database_call(
                lambda: self._verify(actor, conversation_id, run_id, result.revision)
            )
            return result
        except (ValidationError, ValueError, TypeError, KeyError):
            raise ServiceUnavailable("Chat details unavailable") from None

    def _verify(
        self, actor: ActorContext, conversation_id: str, run_id: str, revision: int
    ) -> None:
        with self.database.connection() as c:
            if self._context(c, actor, conversation_id, run_id)["revision"] != revision:
                raise ScopeDenied("Resource unavailable")

    def _snapshot(
        self, actor: ActorContext, conversation_id: str, run_id: str
    ) -> AgentDetailSnapshot:
        with self.database.connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            row = self._context(c, actor, conversation_id, run_id)
            state = ConversationState.model_validate(row["state"])
            now = db_now(c)
            summary = (
                self._summary(c, actor, conversation_id, row["scenario_run_no"], state)
                if row["requested_action"] is not None
                else None
            )
            return AgentDetailSnapshot(
                run_id=run_id,
                revision=row["revision"],
                checked_at=now,
                simulation_at=sim_now(c, actor.tenant_id),
                summary=summary,
            )

    def _summary(
        self,
        c: PolicyConnection,
        actor: ActorContext,
        conversation_id: str,
        scenario: int,
        state: ConversationState,
    ) -> AgentActionSummary | None:
        intent_row, payment = None, None
        draft = state.tuition
        if state.active_intent in {Intent.TRACK, Intent.RECOVER}:
            if state.recovery.payment_id is None:
                return None
            payment = c.execute(
                "SELECT * FROM transfers WHERE tenant_id=%s AND alias=%s",
                (actor.tenant_id, state.recovery.payment_id),
            ).fetchone()
            if payment is None:
                raise ScopeDenied("Resource unavailable")
            intent_row = fetch(c, "intent", actor.tenant_id, payment["intent_alias"])
            if intent_row is None:
                raise ScopeDenied("Resource unavailable")
            obligation_id = state.recovery.obligation_id
            if payment["obligation_alias"] != obligation_id:
                raise ScopeDenied("Resource unavailable")
        elif state.active_intent in {Intent.TUITION, Intent.VERIFY_MESSAGE}:
            obligation_id = draft.obligation_id
            proposal = proposal_of(draft)
            if proposal:
                key = ConversationKey(
                    tenant_id=actor.tenant_id,
                    actor_id=actor.actor_id,
                    session_id=actor.session_id,
                    conversation_id=conversation_id,
                )
                action = TuitionActions.record_for_proposal(c, key, scenario, proposal)
                if action:
                    intent_row = fetch(c, "intent", actor.tenant_id, action["intent_id"])
                    if intent_row is None or intent_row["terms_hash"] != action["terms_hash"]:
                        raise ScopeDenied("Resource unavailable")
            if state.active_intent == Intent.VERIFY_MESSAGE and intent_row is None:
                return None
        else:
            return None
        if obligation_id is None:
            return None
        obligation = fetch(c, "obligation", actor.tenant_id, obligation_id)
        if obligation is None or obligation["student_id"] != actor.actor_id:
            raise ScopeDenied("Resource unavailable")
        if intent_row is not None:
            if (
                intent_row["requested_by"] != actor.actor_id
                or intent_row["obligation_alias"] != obligation_id
                or intent_row["purpose"] != "TUITION"
            ):
                raise ScopeDenied("Resource unavailable")
            if payment is None:
                payment = c.execute(
                    "SELECT * FROM transfers WHERE tenant_id=%s AND intent_alias=%s",
                    (actor.tenant_id, intent_row["alias"]),
                ).fetchone()
            if payment and payment["obligation_alias"] != obligation_id:
                raise ScopeDenied("Resource unavailable")
        detail = self.finance.obligations._detail(c, actor.tenant_id, obligation)
        result: dict[str, object] = {
            "obligation": AgentTuitionDetail.model_validate(
                {name: getattr(detail, name) for name in AgentTuitionDetail.model_fields}
            ),
            "beneficiary": "Not selected",
            "funding": "Not selected",
        }
        account_id = intent_row["source_account_alias"] if intent_row else draft.source_account_id
        beneficiary_id = intent_row["beneficiary_alias"] if intent_row else draft.beneficiary_id
        quote_id = intent_row["quote_alias"] if intent_row else draft.quote_id
        account = fetch(c, "account", actor.tenant_id, account_id) if account_id else None
        if account_id and (
            account is None
            or (
                intent_row is None
                and (
                    not account["active"]
                    or (
                        account["owner_id"] != actor.actor_id
                        and actor.actor_id not in account["permitted_requesters"]
                    )
                )
            )
        ):
            raise ScopeDenied("Resource unavailable")
        if account:
            result["funding"] = (
                "Your own funding"
                if account["owner_id"] == actor.actor_id
                else "Sponsor-owned funding"
            )
        beneficiary = (
            fetch(c, "beneficiary", actor.tenant_id, beneficiary_id) if beneficiary_id else None
        )
        if beneficiary_id and (
            beneficiary is None
            or not beneficiary["verified"]
            or beneficiary["owner_id"] != obligation["university_id"]
            or (
                intent_row is not None
                and beneficiary["fingerprint"] != intent_row["beneficiary_fingerprint"]
            )
        ):
            raise ScopeDenied("Resource unavailable")
        if beneficiary:
            result["beneficiary"] = label(beneficiary["masked_display"])
        if quote_id:
            stored = fetch(c, "quote", actor.tenant_id, quote_id)
            if stored is None:
                raise ScopeDenied("Resource unavailable")
            quote = quote_from_row(stored)
            expected = (
                intent_row["destination_amount_minor"] if intent_row else detail.balance_minor
            )
            if quote.destination_amount_minor != expected:
                raise ScopeDenied("Resource unavailable")
            if intent_row is not None and (
                quote.source_total_minor != intent_row["source_total_minor"]
                or quote.expires_at != intent_row["quote_expiry"]
            ):
                raise ScopeDenied("Resource unavailable")
            values = {name: getattr(quote, name) for name in AgentQuoteDetail.model_fields}
            values["provider"] = label(quote.provider)
            result["quote"] = AgentQuoteDetail.model_validate(values)
        if intent_row is not None:
            intent = intent_from_row(intent_row)
            result["intent_state"] = intent.state
            held = c.execute(
                "SELECT 1 FROM security_holds WHERE tenant_id=%s AND resource_id=%s "
                "AND state='ACTIVE' LIMIT 1",
                (actor.tenant_id, intent.id),
            ).fetchone()
            if held:
                result["intent_state"] = PaymentState.ON_HOLD
            approval = c.execute(
                "SELECT * FROM approvals WHERE tenant_id=%s AND intent_id=%s "
                "AND intent_revision=%s ORDER BY created_at DESC,id DESC LIMIT 1",
                (actor.tenant_id, intent.id, intent.intent_revision),
            ).fetchone()
            if approval:
                record = AuthorityStore.approval(approval)
                status = record.state
                if (
                    terms_of(record) != terms_of(intent)
                    or approval["owner_id"] != intent.funding_owner_id
                    or record.approver_actor_id != intent.funding_owner_id
                ):
                    status = ApprovalState.INVALIDATED_BY_CHANGE
                elif status in {
                    ApprovalState.REQUESTED,
                    ApprovalState.PENDING,
                    ApprovalState.APPROVED,
                } and record.expires_at <= db_now(c):
                    status = ApprovalState.EXPIRED
                result["approval"] = AgentApprovalDetail(
                    state=status,
                    expires_at=record.expires_at,
                    owner="SELF" if intent.funding_owner_id == actor.actor_id else "OTHER",
                )
        if payment:
            linked = c.execute(
                "SELECT 1 FROM university_postings WHERE tenant_id=%s AND transfer_alias=%s "
                "AND obligation_alias=%s AND posted_minor>0 LIMIT 1",
                (actor.tenant_id, payment["alias"], obligation_id),
            ).fetchone()
            result["payment"] = AgentPaymentDetail(
                transfer_status=PaymentState(payment["state"]),
                linked_posting=bool(linked),
            )
            case = c.execute(
                "SELECT * FROM reconciliation_cases WHERE tenant_id=%s AND transfer_alias=%s "
                "AND obligation_alias=%s ORDER BY created_at DESC,alias DESC LIMIT 1",
                (actor.tenant_id, payment["alias"], obligation_id),
            ).fetchone()
            if state.active_intent in {Intent.TRACK, Intent.RECOVER} and state.recovery.case_id:
                case = c.execute(
                    "SELECT * FROM reconciliation_cases WHERE tenant_id=%s AND alias=%s "
                    "AND transfer_alias=%s AND obligation_alias=%s",
                    (actor.tenant_id, state.recovery.case_id, payment["alias"], obligation_id),
                ).fetchone()
                if case is None:
                    raise ScopeDenied("Resource unavailable")
            if case:
                result["case"] = AgentRecoveryDetail(
                    state=case["state"],
                    evidence_missing=tuple(
                        EVIDENCE.get(code, "Additional evidence requires authorized review")
                        for code in case["evidence_missing"][:10]
                    ),
                )
        return AgentActionSummary.model_validate(result)
