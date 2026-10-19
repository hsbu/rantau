"""Create, revise and cancel payment intents. Terms are server-derived and immutable."""

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

FIRST_REVISION = 1
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
            return self.create_in_transaction(connection, actor, proposal)

    def create_in_transaction(
        self, connection: PolicyConnection, actor: ActorContext, proposal: IntentProposal
    ) -> Created | Refused:
        """Compose a proposal with durable caller correlation on the same gated transaction."""
        return self._create(connection, actor, proposal, FIRST_REVISION, None)

    def revise(
        self, actor: ActorContext, intent_alias: str, proposal: IntentProposal
    ) -> Created | Refused:
        """Replace an unstarted intent with a new immutable revision; the old one is cancelled."""
        with self.database.connection() as connection:
            return self.revise_in_transaction(connection, actor, intent_alias, proposal)

    def revise_in_transaction(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        intent_alias: str,
        proposal: IntentProposal,
    ) -> Created | Refused:
        """Compose the existing revision with caller correlation on the same transaction."""
        locked = lock_intent(connection, actor.tenant_id, intent_alias)
        if locked.intent["requested_by"] != actor.actor_id:
            raise ScopeDenied("Resource unavailable")
        require_transition(
            INTENT_TRANSITIONS, PaymentState(locked.intent["state"]), PaymentState.CANCELLED
        )
        facts = _ProposalFacts.load(connection, actor, proposal)
        if facts.refusal is not None:
            return self._refuse(connection, actor, facts.refusal, None)
        cancelled = _set_state(connection, locked.intent, PaymentState.CANCELLED)
        self._audit(connection, actor, "INTENT_SUPERSEDED", cancelled.id, cancelled.state)
        revision = locked.intent["intent_revision"] + 1
        return self._create(connection, actor, proposal, revision, intent_alias, facts)

    def cancel(self, actor: ActorContext, intent_alias: str) -> PaymentIntent:
        with self.database.connection() as connection:
            return self.cancel_in_transaction(connection, actor, intent_alias)

    def cancel_in_transaction(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        intent_alias: str,
    ) -> PaymentIntent:
        """Compose cancellation with authority invalidation on the same transaction."""
        locked = lock_intent(connection, actor.tenant_id, intent_alias)
        if not may_view(actor.actor_id, locked.intent):
            raise ScopeDenied("Resource unavailable")
        current = PaymentState(locked.intent["state"])
        require_transition(INTENT_TRANSITIONS, current, PaymentState.CANCELLED)
        updated = _set_state(connection, locked.intent, PaymentState.CANCELLED)
        self._audit(connection, actor, "INTENT_CANCELLED", updated.id, updated.state)
        return updated

    def _create(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        proposal: IntentProposal,
        revision: int,
        supersedes: str | None,
        loaded: "_ProposalFacts | None" = None,
    ) -> Created | Refused:
        facts = loaded or _ProposalFacts.load(connection, actor, proposal)
        if facts.refusal is not None:
            return self._refuse(connection, actor, facts.refusal, None)
        intent = _insert_draft(connection, actor, facts, revision, supersedes)
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
            return self._refuse(connection, actor, decision.reason_code, decision)
        stored = _settle_draft(connection, actor.tenant_id, intent, decision)
        self._audit(connection, actor, "INTENT_CREATED", stored.id, stored.state, decision)
        return Created(stored, decision)

    def _refuse(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        reason: ReasonCode | None,
        decision: PolicyDecision | None,
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
    """Server-side facts behind a proposal. The client names resources, never amounts."""

    def __init__(
        self,
        purpose: str,
        obligation: Row | None,
        account: Row,
        beneficiary: Row | None,
        quote: Row,
        balance_minor: int | None,
        policy_version: str,
    ):
        self.purpose = purpose
        self.obligation = obligation
        self.account = account
        self.beneficiary = beneficiary
        self.quote = quote
        self.balance_minor = balance_minor
        self.policy_version = policy_version

    @property
    def refusal(self) -> ReasonCode | None:
        if self.beneficiary is None:
            return ReasonCode.UNKNOWN_BENEFICIARY
        wrong_currency = self.quote["source_currency"] != self.account["currency"]
        wrong_amount = (
            self.balance_minor is not None
            and self.quote["destination_amount_minor"] != self.balance_minor
        )
        return ReasonCode.INVALID_SCOPE if wrong_currency or wrong_amount else None

    @classmethod
    def load(
        cls, connection: PolicyConnection, actor: ActorContext, proposal: IntentProposal
    ) -> "_ProposalFacts":
        tenant = actor.tenant_id
        account = fetch(connection, "account", tenant, proposal.source_account_id)
        quote = fetch(connection, "quote", tenant, proposal.quote_id)
        if account is None or quote is None:
            raise ScopeDenied("Resource unavailable")
        if actor.actor_id not in {account["owner_id"], *account["permitted_requesters"]}:
            raise ScopeDenied("Resource unavailable")
        beneficiary = fetch(connection, "beneficiary", tenant, proposal.beneficiary_id)
        if beneficiary is not None and not _fits_purpose(beneficiary, proposal.purpose, actor):
            beneficiary = None
        if proposal.purpose == "ALLOWANCE":
            if proposal.obligation_id is not None:
                raise ScopeDenied("Resource unavailable")
            return cls(
                "ALLOWANCE",
                None,
                account,
                beneficiary,
                quote,
                None,
                _rules_version(connection, tenant),
            )
        obligation = fetch(connection, "obligation", tenant, proposal.obligation_id or "")
        if obligation is None or obligation["student_id"] != actor.actor_id:
            raise ScopeDenied("Resource unavailable")
        balance = read_obligation(
            connection, tenant, obligation, sim_now(connection, tenant)
        ).obligation.balance_minor
        return cls(
            "TUITION", obligation, account, beneficiary, quote, balance, obligation["policy_alias"]
        )


def _fits_purpose(beneficiary: Row, purpose: str, actor: ActorContext) -> bool:
    if beneficiary["purpose_type"] != purpose:
        return False
    return purpose == "TUITION" or beneficiary["student_id"] == actor.actor_id


def _rules_version(connection: PolicyConnection, tenant_id: str) -> str:
    row = connection.execute(
        "SELECT version FROM payment_rules WHERE tenant_id = %s "
        "ORDER BY effective_from DESC LIMIT 1",
        (tenant_id,),
    ).fetchone()
    if row is None:
        raise ScopeDenied("Resource unavailable")
    return str(row["version"])


def _insert_draft(
    connection: PolicyConnection,
    actor: ActorContext,
    facts: _ProposalFacts,
    revision: int,
    supersedes: str | None,
) -> PaymentIntent:
    alias = f"intent_{uuid4().hex[:12]}"
    terms = _terms(alias, facts, revision)
    connection.execute(
        "INSERT INTO payment_intents (tenant_id, alias, requested_by, funding_owner_id, "
        "source_account_alias, beneficiary_alias, beneficiary_fingerprint, obligation_alias, "
        "purpose, source_currency, destination_currency, source_total_minor, "
        "destination_amount_minor, quote_alias, quote_expiry, policy_version, intent_revision, "
        "terms_hash, tier, state, supersedes_alias) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, "
        "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
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
            _starting_tier(terms.purpose).value,
            PaymentState.DRAFT.value,
            supersedes,
        ),
    )
    row = fetch(connection, "intent", actor.tenant_id, alias)
    assert row is not None
    return intent_from_row(row)


def _starting_tier(purpose: str) -> Tier:
    """The stored tier is a floor for the gate, so a routine allowance must start low."""
    return Tier.T1 if purpose == "ALLOWANCE" else Tier.T2


def _terms(alias: str, facts: _ProposalFacts, revision: int) -> PaymentTerms:
    assert facts.beneficiary is not None
    quote, account = facts.quote, facts.account
    unsigned = PaymentTerms(
        intent_id=alias,
        intent_revision=revision,
        funding_owner_id=account["owner_id"],
        source_account_id=account["alias"],
        beneficiary_id=facts.beneficiary["alias"],
        beneficiary_fingerprint=facts.beneficiary["fingerprint"],
        purpose=facts.purpose,  # type: ignore[arg-type]
        obligation_id=facts.obligation["alias"] if facts.obligation else None,
        source_currency=quote["source_currency"],
        destination_currency=quote["destination_currency"],
        source_total_minor=quote["source_total_minor"],
        destination_amount_minor=quote["destination_amount_minor"],
        quote_id=quote["alias"],
        quote_expiry=quote["expires_at"],
        policy_version=facts.policy_version,
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
