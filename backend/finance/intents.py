"""Create and cancel payment intents. Terms are server-derived and immutable."""

from uuid import uuid4

from backend.authz.policy_repository import PolicyConnection
from backend.authz.storage import Database
from backend.contracts.enums import Decision, PaymentState, ReasonCode, Tier
from backend.contracts.models import (
    ActionIntent,
    ActorContext,
    IntentProposal,
    PaymentIntent,
    PaymentTerms,
    PolicyDecision,
    ScopeDenied,
)
from backend.finance.audit import AuditEvent, AuditWriter
from backend.finance.authorization import GateFactory, evaluate_gate
from backend.finance.outcomes import Created, Refused
from backend.finance.records import Row, fetch, intent_from_row, lock_intent, may_view
from backend.finance.simclock import sim_now
from backend.finance.states import INTENT_TRANSITIONS, require_transition
from backend.finance.terms import canonical_terms_hash
from backend.university.obligations import read_obligation

_STATE_AFTER_DECISION = {
    Decision.ALLOW: PaymentState.DRAFT,
    Decision.REQUIRE_APPROVAL: PaymentState.AWAITING_APPROVAL,
    Decision.HOLD: PaymentState.ON_HOLD,
}


class IntentService:
    def __init__(self, database: Database, gate: GateFactory, audit: AuditWriter | None = None):
        self.database = database
        self.gate = gate
        self.audit = audit or AuditWriter()

    def create(self, actor: ActorContext, proposal: IntentProposal) -> Created | Refused:
        with self.database.connection() as connection:
            return self._create(connection, actor, proposal)

    def cancel(self, actor: ActorContext, intent_alias: str) -> PaymentIntent:
        with self.database.connection() as connection:
            locked = lock_intent(connection, actor.tenant_id, intent_alias)
            if not may_view(actor.actor_id, locked.intent):
                raise ScopeDenied("Resource unavailable")
            current = PaymentState(locked.intent["state"])
            require_transition(INTENT_TRANSITIONS, current, PaymentState.CANCELLED)
            updated = _set_state(connection, locked.intent, PaymentState.CANCELLED)
            self._audit(connection, actor, "INTENT_CANCELLED", updated.id, updated.state)
            return updated

    def _create(
        self, connection: PolicyConnection, actor: ActorContext, proposal: IntentProposal
    ) -> Created | Refused:
        facts = _ProposalFacts.load(connection, actor, proposal)
        if facts.beneficiary is None:
            return self._refuse(connection, actor, ReasonCode.UNKNOWN_BENEFICIARY, proposal)
        if facts.mismatched:
            return self._refuse(connection, actor, ReasonCode.INVALID_SCOPE, proposal)
        intent = _insert_draft(connection, actor, facts)
        decision = evaluate_gate(
            self.gate,
            connection,
            actor,
            ActionIntent(
                action="CREATE_INTENT", resource_id=intent.id, terms_hash=intent.terms_hash
            ),
        )
        if decision.decision == Decision.DENY:
            _discard_draft(connection, actor.tenant_id, intent.id)
            return self._refuse(connection, actor, decision.reason_code, proposal, decision)
        stored = _settle_draft(connection, actor.tenant_id, intent, decision)
        self._audit(connection, actor, "INTENT_CREATED", stored.id, stored.state, decision)
        return Created(stored, decision)

    def _refuse(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        reason: ReasonCode | None,
        proposal: IntentProposal,
        decision: PolicyDecision | None = None,
    ) -> Refused:
        reason = reason or ReasonCode.INVALID_SCOPE
        audit_id = self.audit.record(
            connection,
            AuditEvent(
                tenant_id=actor.tenant_id,
                actor_id=actor.actor_id,
                action="INTENT_REFUSED",
                resource_type="payment_intent",
                decision=decision.decision.value if decision else Decision.HOLD.value,
                reason_code=reason.value,
            ),
        )
        return Refused(reason, audit_id, decision)

    def _audit(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        action: str,
        resource_id: str,
        state: PaymentState,
        decision: PolicyDecision | None = None,
    ) -> None:
        self.audit.record(
            connection,
            AuditEvent(
                tenant_id=actor.tenant_id,
                actor_id=actor.actor_id,
                action=action,
                resource_type="payment_intent",
                resource_id=resource_id,
                decision=decision.decision.value if decision else None,
                reason_code=decision.reason_code.value
                if decision and decision.reason_code
                else None,
                after_state={"state": state.value},
            ),
        )


class _ProposalFacts:
    def __init__(
        self, obligation: Row, account: Row, beneficiary: Row | None, quote: Row, balance_minor: int
    ):
        self.balance_minor = balance_minor
        self.obligation = obligation
        self.account = account
        self.beneficiary = beneficiary
        self.quote = quote

    @property
    def mismatched(self) -> bool:
        wrong_amount = self.quote["destination_amount_minor"] != self.balance_minor
        wrong_currency = self.quote["source_currency"] != self.account["currency"]
        return bool(wrong_amount or wrong_currency)

    @classmethod
    def load(
        cls, connection: PolicyConnection, actor: ActorContext, proposal: IntentProposal
    ) -> "_ProposalFacts":
        tenant = actor.tenant_id
        obligation = fetch(connection, "obligation", tenant, proposal.obligation_id or "")
        if obligation is None or obligation["student_id"] != actor.actor_id:
            raise ScopeDenied("Resource unavailable")
        account = fetch(connection, "account", tenant, proposal.source_account_id)
        quote = fetch(connection, "quote", tenant, proposal.quote_id)
        if account is None or quote is None:
            raise ScopeDenied("Resource unavailable")
        if actor.actor_id not in {account["owner_id"], *account["permitted_requesters"]}:
            raise ScopeDenied("Resource unavailable")
        balance = read_obligation(
            connection, tenant, obligation, sim_now(connection, tenant)
        ).obligation.balance_minor
        beneficiary = fetch(connection, "beneficiary", tenant, proposal.beneficiary_id)
        return cls(obligation, account, beneficiary, quote, balance)


def _insert_draft(
    connection: PolicyConnection, actor: ActorContext, facts: _ProposalFacts
) -> PaymentIntent:
    assert facts.beneficiary is not None
    alias = f"intent_{uuid4().hex[:12]}"
    terms = _terms(alias, actor, facts)
    connection.execute(
        "INSERT INTO payment_intents (tenant_id, alias, requested_by, funding_owner_id, "
        "source_account_alias, beneficiary_alias, beneficiary_fingerprint, obligation_alias, "
        "purpose, source_currency, destination_currency, source_total_minor, "
        "destination_amount_minor, quote_alias, quote_expiry, policy_version, intent_revision, "
        "terms_hash, tier, state) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
        "%s, %s, %s, %s, %s, %s, %s)",
        (
            actor.tenant_id,
            alias,
            actor.actor_id,
            terms.funding_owner_id,
            terms.source_account_id,
            terms.beneficiary_id,
            terms.beneficiary_fingerprint,
            terms.obligation_id,
            terms.purpose,
            terms.source_currency.value,
            terms.destination_currency.value,
            terms.source_total_minor,
            terms.destination_amount_minor,
            terms.quote_id,
            terms.quote_expiry,
            terms.policy_version,
            terms.intent_revision,
            terms.terms_hash,
            Tier.T2.value,
            PaymentState.DRAFT.value,
        ),
    )
    row = fetch(connection, "intent", actor.tenant_id, alias)
    assert row is not None
    return intent_from_row(row)


def _terms(alias: str, actor: ActorContext, facts: _ProposalFacts) -> PaymentTerms:
    assert facts.beneficiary is not None
    quote, account, obligation = facts.quote, facts.account, facts.obligation
    unsigned = PaymentTerms(
        intent_id=alias,
        intent_revision=1,
        funding_owner_id=account["owner_id"],
        source_account_id=account["alias"],
        beneficiary_id=facts.beneficiary["alias"],
        beneficiary_fingerprint=facts.beneficiary["fingerprint"],
        purpose="TUITION",
        obligation_id=obligation["alias"],
        source_currency=quote["source_currency"],
        destination_currency=quote["destination_currency"],
        source_total_minor=quote["source_total_minor"],
        destination_amount_minor=quote["destination_amount_minor"],
        quote_id=quote["alias"],
        quote_expiry=quote["expires_at"],
        policy_version=obligation["policy_alias"],
        terms_hash="pending",
    )
    return unsigned.model_copy(update={"terms_hash": canonical_terms_hash(unsigned)})


def _discard_draft(connection: PolicyConnection, tenant_id: str, alias: str) -> None:
    connection.execute(
        "DELETE FROM payment_intents WHERE tenant_id = %s AND alias = %s", (tenant_id, alias)
    )


def _settle_draft(
    connection: PolicyConnection, tenant_id: str, intent: PaymentIntent, decision: PolicyDecision
) -> PaymentIntent:
    target = _STATE_AFTER_DECISION[decision.decision]
    if target != intent.state:
        require_transition(INTENT_TRANSITIONS, intent.state, target)
    row = connection.execute(
        "UPDATE payment_intents SET state = %s, tier = %s, version = version + 1 "
        "WHERE tenant_id = %s AND alias = %s RETURNING *",
        (target.value, decision.tier.value, tenant_id, intent.id),
    ).fetchone()
    assert row is not None
    return intent_from_row(row)


def _set_state(connection: PolicyConnection, row: Row, target: PaymentState) -> PaymentIntent:
    updated = connection.execute(
        "UPDATE payment_intents SET state = %s, version = version + 1 "
        "WHERE tenant_id = %s AND alias = %s AND version = %s RETURNING *",
        (target.value, row["tenant_id"], row["alias"], row["version"]),
    ).fetchone()
    if updated is None:
        raise ScopeDenied("Resource unavailable")
    return intent_from_row(updated)
