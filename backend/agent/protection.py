"""Bind deterministic B findings to an existing, current, confirmed student action."""

from backend.agent.actions import Correlation, TuitionActions, proposal_of
from backend.agent.persistence import _database_call
from backend.agent.state import ConversationKey, TuitionDraft
from backend.contracts.enums import Intent, PaymentState
from backend.contracts.http import AgentResponse, ResourceReference, ToolEvent
from backend.contracts.models import ActorContext, IntentProposal, ScopeDenied
from backend.finance.records import fetch, lock_intent
from backend.fraud.finance_access import build_security_service
from backend.fraud.models import AdvisorySignal, HardFinding, TrustedFraudFacts
from backend.fraud.rules import hard_findings, local_advisory_signals
from backend.fraud.security_cases import SecurityReason


class AgentProtection:
    def __init__(self, actions: TuitionActions) -> None:
        self.actions = actions
        self.security = build_security_service(actions.auth)

    async def check(
        self,
        message: str,
        actor: ActorContext,
        key: ConversationKey | None,
        draft: TuitionDraft,
    ) -> AgentResponse | None:
        proposal = proposal_of(draft)
        if key is None or proposal is None:
            return None
        record = await _database_call(
            lambda: self.actions._prepare(key, proposal, actor, create=False)
        )
        if not isinstance(record, Correlation):
            return None
        result = await _database_call(lambda: self._hold(message, actor, key, proposal, record))
        if result is None:
            return None
        case_id, created = result
        return AgentResponse(
            run_id="pending",
            requested_action=Intent.VERIFY_MESSAGE,
            message="**Payment on hold**\n\nThe current confirmed request is blocked "
            "pending separate trusted security review. Its recipient is unchanged. "
            "Chat cannot clear this hold or authorize a replacement payment.",
            resources=(ResourceReference(kind="case", id=case_id),),
            tool_events=(
                ToolEvent(tool="assess_fraud_risk", status="OK"),
                ToolEvent(tool="place_security_hold", status="OK"),
                ToolEvent(
                    tool="create_security_case" if created else "get_security_case",
                    status="OK",
                    resource_id=case_id,
                ),
            ),
        )

    def _hold(
        self,
        message: str,
        actor: ActorContext,
        key: ConversationKey,
        proposal: IntentProposal,
        record: Correlation,
    ) -> tuple[str, bool] | None:
        with self.actions.database.connection() as c:
            scenario = self.actions._context(c, key, actor)
            if self.actions._key(key, scenario, proposal) != record.action_key:
                raise ScopeDenied("Resource unavailable")
            locked = lock_intent(c, actor.tenant_id, record.intent_id)
            if self.actions._scenario(c, actor.tenant_id) != scenario:
                raise ScopeDenied("Resource unavailable")
            self.actions._require(c, actor)
            intent = locked.intent
            if (
                intent["requested_by"] != actor.actor_id
                or intent["terms_hash"] != record.terms_hash
            ):
                raise ScopeDenied("Resource unavailable")
            if PaymentState(intent["state"]) not in {
                PaymentState.DRAFT,
                PaymentState.AWAITING_APPROVAL,
                PaymentState.AUTHORIZED,
                PaymentState.ON_HOLD,
            }:
                return None
            beneficiary = fetch(c, "beneficiary", actor.tenant_id, intent["beneficiary_alias"])
            obligation = locked.obligation
            facts = TrustedFraudFacts(
                beneficiary_verified=bool(beneficiary and beneficiary["verified"]),
                beneficiary_matches_current_intent=bool(
                    beneficiary
                    and obligation
                    and beneficiary["fingerprint"] == intent["beneficiary_fingerprint"]
                    and beneficiary["owner_id"] == obligation["university_id"]
                ),
                beneficiary_change_requested=False,
            )
            hard = hard_findings(message, facts)
            reason = next(
                (
                    reason
                    for finding, reason in (
                        (HardFinding.BENEFICIARY_MISMATCH, SecurityReason.BENEFICIARY_MISMATCH),
                        (HardFinding.BENEFICIARY_UNVERIFIED, SecurityReason.UNKNOWN_BENEFICIARY),
                        (
                            HardFinding.BENEFICIARY_CHANGE_REQUESTED,
                            SecurityReason.BENEFICIARY_CHANGE_REQUESTED,
                        ),
                    )
                    if finding in hard
                ),
                None,
            )
            if reason is None and AdvisorySignal.PROMPT_INJECTION in local_advisory_signals(
                message
            ):
                reason = SecurityReason.PROMPT_INJECTION
            if reason is None:
                return None
            self.security.place_hold(c, actor, record.intent_id, reason)
            existing = c.execute(
                "SELECT case_id FROM security_cases WHERE tenant_id=%s AND resource_id=%s "
                "AND state IN ('OPEN','UNDER_REVIEW','ESCALATED') ORDER BY created_at DESC LIMIT 1",
                (actor.tenant_id, record.intent_id),
            ).fetchone()
            case_id = (
                existing["case_id"]
                if existing
                else self.security.create_case(
                    c, actor, record.intent_id, reason, ("action_" + record.action_key,)
                ).case_id
            )
            self.actions._require(c, actor)
            return str(case_id), existing is None
