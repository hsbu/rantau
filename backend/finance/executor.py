"""Protected execution: gate, re-checks, debit, ledger and transfer in one transaction.

The provider is called only after the debit commits; TransferService applies the outcome.
"""

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

from backend.authz.policy_repository import PolicyConnection
from backend.authz.storage import Database
from backend.contracts.enums import Decision, PaymentState, ReasonCode
from backend.contracts.models import (
    ActionIntent,
    ActorContext,
    PaymentTerms,
    PolicyDecision,
    ScopeDenied,
    ServiceUnavailable,
)
from backend.finance.audit import AuditEvent, AuditWriter
from backend.finance.authorization import GateFactory, evaluate_gate
from backend.finance.clock import db_now, period_starts
from backend.finance.outcomes import Executed, Refused
from backend.finance.records import LockedIntent, Row, fetch, intent_from_row, lock_intent, may_view
from backend.finance.states import INTENT_TRANSITIONS, require_transition
from backend.finance.terms import canonical_terms_hash
from backend.finance.transfers import FINAL_STATES, TransferService

# Keys of settled payments are kept long enough to absorb client retries.
IDEMPOTENCY_RETENTION = timedelta(days=1)
CLEARING_ACCOUNT = "system:provider_clearing"
FEE_ACCOUNT = "system:fee_revenue"
ExecutionFinalizer = Callable[[PolicyConnection, ActorContext, LockedIntent, PolicyDecision], None]


class IdempotencyKeyReused(Exception):
    """The key was already used for a different request."""


class ExecutionService:
    def __init__(
        self,
        database: Database,
        gate: GateFactory,
        transfers: TransferService,
        audit: AuditWriter | None = None,
        *,
        finalize_authorization: ExecutionFinalizer | None = None,
    ):
        self.database = database
        self.gate = gate
        self.transfers = transfers
        self.audit = audit or AuditWriter()
        self.finalize_authorization = finalize_authorization

    def execute(
        self,
        actor: ActorContext,
        intent_alias: str,
        idempotency_key: str,
        claimed_terms_hash: str | None = None,
    ) -> Executed | Refused:
        outcome = self._decide_and_debit(actor, intent_alias, idempotency_key, claimed_terms_hash)
        if isinstance(outcome, Refused) or outcome.transfer_state in FINAL_STATES:
            return outcome
        state = self.transfers.settle(actor.tenant_id, outcome.payment_id)
        return replace(outcome, transfer_state=state)

    def _decide_and_debit(
        self,
        actor: ActorContext,
        intent_alias: str,
        idempotency_key: str,
        claimed_terms_hash: str | None = None,
    ) -> Executed | Refused:
        with self.database.connection() as connection:
            locked = lock_intent(connection, actor.tenant_id, intent_alias)
            if not may_view(actor.actor_id, locked.intent):
                raise ScopeDenied("Resource unavailable")
            fingerprint = _fingerprint(locked.intent, claimed_terms_hash)
            replay = _replay(connection, actor, idempotency_key, fingerprint)
            if replay is not None:
                return replay
            broken = _integrity_failure(locked)
            if broken is not None:
                return self._refuse(connection, actor, intent_alias, broken)
            decision = evaluate_gate(
                self.gate,
                connection,
                actor,
                ActionIntent(
                    action="EXECUTE_PAYMENT",
                    resource_id=intent_alias,
                    terms_hash=claimed_terms_hash or locked.intent["terms_hash"],
                ),
            )
            if decision.decision != Decision.ALLOW:
                assert decision.reason_code is not None
                return self._refuse(connection, actor, intent_alias, decision.reason_code, decision)
            executed = self._debit(
                connection, actor, locked, idempotency_key, fingerprint, decision
            )
            if self.finalize_authorization is not None:
                self.finalize_authorization(connection, actor, locked, decision)
            return executed

    def _debit(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        locked: LockedIntent,
        key: str,
        fingerprint: str,
        decision: PolicyDecision,
    ) -> Executed:
        intent, account = locked.intent, locked.account
        quote = fetch(connection, "quote", actor.tenant_id, intent["quote_alias"])
        if quote is None:
            raise ServiceUnavailable("Quote unavailable")
        total = intent["source_total_minor"]
        _require_within_limits(connection, actor.tenant_id, account, total)
        _debit_account(connection, actor.tenant_id, account["alias"], total)
        transfer_alias = f"transfer_{uuid4().hex[:12]}"
        _insert_transfer(connection, actor.tenant_id, intent, quote, transfer_alias)
        _insert_ledger_legs(connection, actor.tenant_id, transfer_alias, account, quote)
        connection.execute(
            "INSERT INTO spend_entries (tenant_id, intent_alias, account_alias, amount_minor, "
            "currency, state) VALUES (%s, %s, %s, %s, %s, 'COMPLETED')",
            (actor.tenant_id, intent["alias"], account["alias"], total, account["currency"]),
        )
        _start_processing(connection, intent)
        audit_id = self.audit.record(
            connection,
            AuditEvent(
                tenant_id=actor.tenant_id,
                actor_id=actor.actor_id,
                action="PAYMENT_DEBITED",
                resource_type="transfer",
                resource_id=transfer_alias,
                decision=decision.decision.value,
                after_state={
                    "state": PaymentState.PROCESSING.value,
                    "source_total_minor": total,
                    "currency": account["currency"],
                    "tier": decision.tier.value,
                },
            ),
        )
        connection.execute(
            "INSERT INTO idempotency_keys (tenant_id, actor_id, key, fingerprint, intent_alias, "
            "transfer_alias, audit_event_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                actor.tenant_id,
                actor.actor_id,
                key,
                fingerprint,
                intent["alias"],
                transfer_alias,
                audit_id,
            ),
        )
        return Executed(transfer_alias, PaymentState.PROCESSING, audit_id)

    def _refuse(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        intent_alias: str,
        reason: ReasonCode,
        decision: PolicyDecision | None = None,
    ) -> Refused:
        audit_id = self.audit.record(
            connection,
            AuditEvent(
                tenant_id=actor.tenant_id,
                actor_id=actor.actor_id,
                action="EXECUTION_REFUSED",
                resource_type="payment_intent",
                resource_id=intent_alias,
                decision=decision.decision.value if decision else Decision.HOLD.value,
                reason_code=reason.value,
            ),
        )
        return Refused(reason, audit_id, decision)


def _fingerprint(intent: Row, claimed_terms_hash: str | None) -> str:
    material = "|".join(
        (
            intent["alias"],
            str(intent["intent_revision"]),
            intent["terms_hash"],
            claimed_terms_hash or "",
        )
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _replay(
    connection: PolicyConnection, actor: ActorContext, key: str, fingerprint: str
) -> Executed | None:
    stored = connection.execute(
        "SELECT k.fingerprint, k.transfer_alias, k.audit_event_id, t.state FROM idempotency_keys k "
        "JOIN transfers t ON t.tenant_id = k.tenant_id AND t.alias = k.transfer_alias "
        "WHERE k.tenant_id = %s AND k.actor_id = %s AND k.key = %s",
        (actor.tenant_id, actor.actor_id, key),
    ).fetchone()
    if stored is None:
        return None
    if stored["fingerprint"] != fingerprint:
        raise IdempotencyKeyReused()
    return Executed(
        stored["transfer_alias"], PaymentState(stored["state"]), stored["audit_event_id"], True
    )


def _integrity_failure(locked: LockedIntent) -> ReasonCode | None:
    """Independent of the gate: stored terms must still match their digest and the owner."""
    intent = intent_from_row(locked.intent)
    terms = PaymentTerms(**{name: getattr(intent, name) for name in PaymentTerms.model_fields})
    if canonical_terms_hash(terms) != locked.intent["terms_hash"]:
        return ReasonCode.SECURITY_HOLD
    if locked.account["owner_id"] != locked.intent["funding_owner_id"]:
        return ReasonCode.INVALID_SCOPE
    return None


def _require_within_limits(
    connection: PolicyConnection, tenant_id: str, account: Row, total: int
) -> None:
    day_start, month_start = period_starts(db_now(connection), account["timezone"])
    spent = connection.execute(
        "SELECT COALESCE(sum(amount_minor) FILTER (WHERE at >= %s), 0) AS day, "
        "COALESCE(sum(amount_minor), 0) AS month FROM spend_entries "
        "WHERE tenant_id = %s AND account_alias = %s AND state = 'COMPLETED' AND at >= %s",
        (day_start, tenant_id, account["alias"], month_start),
    ).fetchone()
    assert spent is not None
    if (
        total > account["per_transfer_limit_minor"]
        or spent["day"] + total > account["daily_limit_minor"]
        or spent["month"] + total > account["monthly_limit_minor"]
    ):
        raise ServiceUnavailable("Execution invariant failed: limits")


def _debit_account(connection: PolicyConnection, tenant_id: str, alias: str, total: int) -> None:
    updated = connection.execute(
        "UPDATE funding_accounts SET balance_minor = balance_minor - %s, version = version + 1 "
        "WHERE tenant_id = %s AND alias = %s AND balance_minor >= %s",
        (total, tenant_id, alias, total),
    )
    if updated.rowcount != 1:
        raise ServiceUnavailable("Execution invariant failed: balance")


def _insert_transfer(
    connection: PolicyConnection, tenant_id: str, intent: Row, quote: Row, alias: str
) -> None:
    connection.execute(
        "INSERT INTO transfers (tenant_id, alias, intent_alias, account_alias, obligation_alias, "
        "beneficiary_alias, provider, provider_reference, state, source_total_minor, "
        "destination_amount_minor, blocks_obligation) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PROCESSING', %s, %s, %s)",
        (
            tenant_id,
            alias,
            intent["alias"],
            intent["source_account_alias"],
            intent["obligation_alias"],
            intent["beneficiary_alias"],
            quote["provider"],
            f"sim_ref_{uuid4().hex[:16]}",
            intent["source_total_minor"],
            intent["destination_amount_minor"],
            intent["obligation_alias"] is not None,
        ),
    )


def _insert_ledger_legs(
    connection: PolicyConnection, tenant_id: str, transfer_alias: str, account: Row, quote: Row
) -> None:
    currency = account["currency"]
    legs = (
        ("DEBIT_FUNDING", f"funding:{account['alias']}", "DEBIT", quote["source_total_minor"]),
        (
            "CREDIT_CLEARING",
            f"{CLEARING_ACCOUNT}:{currency}",
            "CREDIT",
            quote["source_principal_minor"],
        ),
        ("CREDIT_FEE", f"{FEE_ACCOUNT}:{currency}", "CREDIT", quote["fee_minor"]),
    )
    for leg, account_ref, direction, amount in legs:
        connection.execute(
            "INSERT INTO ledger_entries (tenant_id, transfer_alias, leg, account_ref, "
            "direction, amount_minor, currency) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (tenant_id, transfer_alias, leg, account_ref, direction, amount, currency),
        )


def _start_processing(connection: PolicyConnection, intent: Row) -> None:
    require_transition(INTENT_TRANSITIONS, PaymentState(intent["state"]), PaymentState.PROCESSING)
    updated = connection.execute(
        "UPDATE payment_intents SET state = 'PROCESSING', version = version + 1 "
        "WHERE tenant_id = %s AND alias = %s AND version = %s",
        (intent["tenant_id"], intent["alias"], intent["version"]),
    )
    if updated.rowcount != 1:
        raise ServiceUnavailable("Execution invariant failed: intent changed")


def prune_idempotency_keys(
    connection: PolicyConnection, tenant_id: str, older_than: timedelta
) -> int:
    """Drop old keys, but only for transfers that have reached a final state."""
    deleted = connection.execute(
        "DELETE FROM idempotency_keys k USING transfers t "
        "WHERE k.tenant_id = %s AND t.tenant_id = k.tenant_id AND t.alias = k.transfer_alias "
        "AND t.state IN ('DELIVERED', 'FAILED') AND k.created_at < clock_timestamp() - %s",
        (tenant_id, older_than),
    )
    return deleted.rowcount
