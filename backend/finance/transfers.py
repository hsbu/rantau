"""Settle a debited transfer with the provider and apply its outcome exactly once.

The provider is called outside any database transaction. Only authoritative evidence moves
a transfer to DELIVERED or FAILED; silence leaves it OUTCOME_UNKNOWN and blocks new debits.
"""

from typing import Protocol
from uuid import uuid4

from backend.authz.policy_repository import PolicyConnection
from backend.authz.storage import Database
from backend.contracts.enums import PaymentState, ReasonCode
from backend.contracts.models import ScopeDenied
from backend.finance.audit import AuditEvent, AuditWriter
from backend.finance.provider import (
    EvidenceKind,
    ProviderEvidence,
    SimulatedProvider,
    SubmitRequest,
)
from backend.finance.records import Row, lock_intent
from backend.finance.states import INTENT_TRANSITIONS, TRANSFER_TRANSITIONS, require_transition

FINAL_STATES = frozenset({PaymentState.DELIVERED, PaymentState.FAILED})
REVERSAL_LEGS = {
    "CREDIT_CLEARING": ("REV_DEBIT_CLEARING", "DEBIT"),
    "CREDIT_FEE": ("REV_DEBIT_FEE", "DEBIT"),
    "DEBIT_FUNDING": ("REV_CREDIT_FUNDING", "CREDIT"),
}


class DeliveryListener(Protocol):
    """Told, inside the outcome transaction, that funds reached the university."""

    def on_delivered(
        self,
        connection: PolicyConnection,
        tenant_id: str,
        transfer: Row,
        evidence: ProviderEvidence,
    ) -> None: ...


class TransferService:
    def __init__(
        self,
        database: Database,
        provider: SimulatedProvider,
        listener: DeliveryListener,
        audit: AuditWriter | None = None,
    ) -> None:
        self.database = database
        self.provider = provider
        self.listener = listener
        self.audit = audit or AuditWriter()

    def settle(self, tenant_id: str, transfer_alias: str) -> PaymentState:
        """Submit if never sent, otherwise poll the same reference, then apply the outcome."""
        transfer = self._read(tenant_id, transfer_alias)
        if PaymentState(transfer["state"]) in FINAL_STATES:
            return PaymentState(transfer["state"])
        evidence = self._ask_provider(tenant_id, transfer)
        return self._apply(tenant_id, transfer_alias, transfer["version"], evidence)

    def _read(self, tenant_id: str, transfer_alias: str) -> Row:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT t.*, i.requested_by FROM transfers t JOIN payment_intents i "
                "ON i.tenant_id = t.tenant_id AND i.alias = t.intent_alias "
                "WHERE t.tenant_id = %s AND t.alias = %s",
                (tenant_id, transfer_alias),
            ).fetchone()
        if row is None:
            raise ScopeDenied("Resource unavailable")
        return row

    def _ask_provider(self, tenant_id: str, transfer: Row) -> ProviderEvidence:
        if transfer["provider_submitted_at"] is not None:
            return self.provider.status(tenant_id, transfer["provider_reference"])
        return self.provider.submit(
            SubmitRequest(
                tenant_id=tenant_id,
                provider=transfer["provider"],
                reference=transfer["provider_reference"],
                amount_minor=transfer["source_total_minor"],
                destination_minor=transfer["destination_amount_minor"],
                payer_reference=transfer["requested_by"],
            )
        )

    def _apply(
        self, tenant_id: str, transfer_alias: str, expected_version: int, evidence: ProviderEvidence
    ) -> PaymentState:
        with self.database.connection() as connection:
            peek = connection.execute(
                "SELECT intent_alias FROM transfers WHERE tenant_id = %s AND alias = %s",
                (tenant_id, transfer_alias),
            ).fetchone()
            assert peek is not None
            locked = lock_intent(connection, tenant_id, peek["intent_alias"])
            transfer = connection.execute(
                "SELECT * FROM transfers WHERE tenant_id = %s AND alias = %s FOR UPDATE",
                (tenant_id, transfer_alias),
            ).fetchone()
            assert transfer is not None
            current = PaymentState(transfer["state"])
            if transfer["version"] != expected_version or current in FINAL_STATES:
                return current
            target = _target_state(current, evidence)
            updated = self._update_transfer(connection, transfer, target, evidence)
            if target != PaymentState(locked.intent["state"]):
                _mirror_intent(connection, locked.intent, target)
            if target == PaymentState.FAILED:
                _reverse(connection, tenant_id, updated, locked.account)
            if target == PaymentState.DELIVERED:
                self.listener.on_delivered(connection, tenant_id, updated, evidence)
            self._audit(connection, tenant_id, updated, target, evidence)
            return target

    def _update_transfer(
        self,
        connection: PolicyConnection,
        transfer: Row,
        target: PaymentState,
        evidence: ProviderEvidence,
    ) -> Row:
        current = PaymentState(transfer["state"])
        if target != current:
            require_transition(TRANSFER_TRANSITIONS, current, target)
        delivered = target == PaymentState.DELIVERED
        row = connection.execute(
            "UPDATE transfers SET state = %s, version = version + 1, "
            "provider_submitted_at = COALESCE(provider_submitted_at, clock_timestamp()), "
            "delivered_destination_minor = %s, payer_reference = %s, receipt_reference = %s, "
            "blocks_obligation = %s, updated_at = clock_timestamp() "
            "WHERE tenant_id = %s AND alias = %s AND version = %s RETURNING *",
            (
                target.value,
                evidence.delivered_destination_minor if delivered else None,
                evidence.payer_reference if delivered else None,
                f"receipt_{uuid4().hex[:12]}" if delivered else transfer["receipt_reference"],
                target != PaymentState.FAILED,
                transfer["tenant_id"],
                transfer["alias"],
                transfer["version"],
            ),
        ).fetchone()
        assert row is not None
        return row

    def _audit(
        self,
        connection: PolicyConnection,
        tenant_id: str,
        transfer: Row,
        target: PaymentState,
        evidence: ProviderEvidence,
    ) -> None:
        reason = (
            ReasonCode.PROVIDER_OUTCOME_UNKNOWN if target == PaymentState.OUTCOME_UNKNOWN else None
        )
        self.audit.record(
            connection,
            AuditEvent(
                tenant_id=tenant_id,
                action=f"TRANSFER_{target.value}",
                resource_type="transfer",
                resource_id=transfer["alias"],
                reason_code=reason.value if reason else None,
                after_state={"state": target.value},
            ),
        )


def _target_state(current: PaymentState, evidence: ProviderEvidence) -> PaymentState:
    if evidence.kind == EvidenceKind.DELIVERED:
        return PaymentState.DELIVERED
    if evidence.kind == EvidenceKind.REJECTED_NO_DEBIT:
        return PaymentState.FAILED
    if evidence.kind == EvidenceKind.ACCEPTED:
        return current
    return PaymentState.OUTCOME_UNKNOWN if current == PaymentState.PROCESSING else current


def _mirror_intent(connection: PolicyConnection, intent: Row, target: PaymentState) -> None:
    require_transition(INTENT_TRANSITIONS, PaymentState(intent["state"]), target)
    connection.execute(
        "UPDATE payment_intents SET state = %s, version = version + 1 "
        "WHERE tenant_id = %s AND alias = %s",
        (target.value, intent["tenant_id"], intent["alias"]),
    )


def _reverse(connection: PolicyConnection, tenant_id: str, transfer: Row, account: Row) -> None:
    """Undo the debit after authoritative proof that the provider took no funds."""
    legs = connection.execute(
        "SELECT * FROM ledger_entries WHERE tenant_id = %s AND transfer_alias = %s "
        "AND leg = ANY(%s)",
        (tenant_id, transfer["alias"], list(REVERSAL_LEGS)),
    ).fetchall()
    for leg in legs:
        reverse_leg, direction = REVERSAL_LEGS[leg["leg"]]
        connection.execute(
            "INSERT INTO ledger_entries (tenant_id, transfer_alias, leg, account_ref, direction, "
            "amount_minor, currency) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                tenant_id,
                transfer["alias"],
                reverse_leg,
                leg["account_ref"],
                direction,
                leg["amount_minor"],
                leg["currency"],
            ),
        )
    connection.execute(
        "UPDATE funding_accounts SET balance_minor = balance_minor + %s, version = version + 1 "
        "WHERE tenant_id = %s AND alias = %s",
        (transfer["source_total_minor"], tenant_id, account["alias"]),
    )
    connection.execute(
        "UPDATE spend_entries SET state = 'RELEASED' WHERE tenant_id = %s AND intent_alias = %s",
        (tenant_id, transfer["intent_alias"]),
    )
