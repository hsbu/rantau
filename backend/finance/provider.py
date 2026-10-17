"""Simulated payment provider with persistent records and scripted failure modes.

It models an external company: calls use their own short transactions, and a reference
seen once always returns the same authoritative answer, so polling is safe.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from backend.authz.policy_repository import PolicyConnection
from backend.authz.storage import Database
from backend.contracts.enums import FaultMode
from backend.finance.simclock import sim_now

DELAYED_DELIVERY = timedelta(hours=6)
SHORT_PAYMENT_DEDUCTION_MINOR = 150_000


class EvidenceKind(StrEnum):
    ACCEPTED = "ACCEPTED"
    DELIVERED = "DELIVERED"
    REJECTED_NO_DEBIT = "REJECTED_NO_DEBIT"
    UNKNOWN_REFERENCE = "UNKNOWN_REFERENCE"
    NO_RESPONSE = "NO_RESPONSE"


AUTHORITATIVE = frozenset(
    {EvidenceKind.ACCEPTED, EvidenceKind.DELIVERED, EvidenceKind.REJECTED_NO_DEBIT}
)


@dataclass(frozen=True)
class ProviderEvidence:
    kind: EvidenceKind
    delivered_destination_minor: int | None = None
    payer_reference: str | None = None

    @property
    def authoritative(self) -> bool:
        return self.kind in AUTHORITATIVE


@dataclass(frozen=True)
class SubmitRequest:
    tenant_id: str
    provider: str
    reference: str
    amount_minor: int
    destination_minor: int
    payer_reference: str | None


class SimulatedProvider:
    def __init__(self, database: Database) -> None:
        self.database = database

    def submit(self, request: SubmitRequest) -> ProviderEvidence:
        """Idempotent per reference: a repeated submit never creates a second debit."""
        with self.database.connection() as connection:
            existing = self._lookup(connection, request.reference, request.tenant_id)
            if existing is not None:
                return existing
            fault = _take_fault(connection, request.tenant_id, request.provider)
            now = sim_now(connection, request.tenant_id)
            return _record(connection, request, fault, now)

    def status(self, tenant_id: str, reference: str) -> ProviderEvidence:
        with self.database.connection() as connection:
            known = self._lookup(connection, reference, tenant_id)
            return known or ProviderEvidence(EvidenceKind.UNKNOWN_REFERENCE)

    def _lookup(
        self, connection: PolicyConnection, reference: str, tenant_id: str
    ) -> ProviderEvidence | None:
        row = connection.execute(
            "SELECT * FROM sim_provider_transfers WHERE provider_reference = %s AND tenant_id = %s",
            (reference, tenant_id),
        ).fetchone()
        if row is None:
            return None
        return _evidence_from_row(row, sim_now(connection, tenant_id))


def set_fault(
    connection: PolicyConnection, tenant_id: str, provider: str, mode: FaultMode, remaining: int = 1
) -> None:
    connection.execute(
        "INSERT INTO sim_provider_faults (tenant_id, provider, mode, remaining) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT (tenant_id, provider) "
        "DO UPDATE SET mode = EXCLUDED.mode, remaining = EXCLUDED.remaining",
        (tenant_id, provider, mode.value, remaining),
    )


def _take_fault(connection: PolicyConnection, tenant_id: str, provider: str) -> FaultMode | None:
    row = connection.execute(
        "UPDATE sim_provider_faults SET remaining = remaining - 1 "
        "WHERE tenant_id = %s AND provider = %s AND remaining > 0 RETURNING mode",
        (tenant_id, provider),
    ).fetchone()
    return FaultMode(row["mode"]) if row else None


def _record(
    connection: PolicyConnection, request: SubmitRequest, fault: FaultMode | None, now: datetime
) -> ProviderEvidence:
    if fault in (FaultMode.UNAVAILABLE, FaultMode.TIMEOUT_BEFORE_ACCEPT):
        _insert(connection, request, "REJECTED_NO_DEBIT", False, now, None, None)
        if fault == FaultMode.TIMEOUT_BEFORE_ACCEPT:
            return ProviderEvidence(EvidenceKind.NO_RESPONSE)
        return ProviderEvidence(EvidenceKind.REJECTED_NO_DEBIT)
    deliver_after = now + (DELAYED_DELIVERY if fault == FaultMode.DELAYED_DELIVERY else timedelta())
    delivered = request.destination_minor - (
        SHORT_PAYMENT_DEDUCTION_MINOR if fault == FaultMode.SHORT_PAYMENT else 0
    )
    payer = None if fault == FaultMode.REFERENCE_MISSING else request.payer_reference
    _insert(connection, request, "ACCEPTED", True, deliver_after, payer, delivered)
    if fault == FaultMode.TIMEOUT_AFTER_ACCEPT:
        return ProviderEvidence(EvidenceKind.NO_RESPONSE)
    row = connection.execute(
        "SELECT * FROM sim_provider_transfers WHERE provider_reference = %s", (request.reference,)
    ).fetchone()
    assert row is not None
    return _evidence_from_row(row, now)


def _insert(
    connection: PolicyConnection,
    request: SubmitRequest,
    status: str,
    debited: bool,
    deliver_after: datetime,
    payer_reference: str | None,
    delivered_minor: int | None,
) -> None:
    connection.execute(
        "INSERT INTO sim_provider_transfers (provider_reference, tenant_id, provider, "
        "amount_minor, destination_amount_minor, status, debited, deliver_after, "
        "payer_reference, delivered_destination_minor) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            request.reference,
            request.tenant_id,
            request.provider,
            request.amount_minor,
            request.destination_minor,
            status,
            debited,
            deliver_after,
            payer_reference,
            delivered_minor,
        ),
    )


def _evidence_from_row(row: dict, now: datetime) -> ProviderEvidence:  # type: ignore[type-arg]
    if row["status"] == "REJECTED_NO_DEBIT":
        return ProviderEvidence(EvidenceKind.REJECTED_NO_DEBIT)
    if now < row["deliver_after"]:
        return ProviderEvidence(EvidenceKind.ACCEPTED)
    return ProviderEvidence(
        EvidenceKind.DELIVERED, row["delivered_destination_minor"], row["payer_reference"]
    )
