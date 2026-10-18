"""Durable authority reads for C, bound to the authenticated service's tenant."""

from backend.approvals.store import AuthorityStore, terms_of
from backend.authz.policy_models import MandateSnapshot
from backend.authz.policy_repository import PolicyConnection
from backend.contracts.enums import Tier
from backend.contracts.models import Approval, PaymentIntent, ScopeDenied
from backend.finance.authority import HoldState
from backend.finance.records import intent_from_row, lock_intent


class StoredAuthority:
    """Only use behind the configured tenant's real session/transaction gate.

    Lock the owning account/obligation/intent before B rows, including when no
    active hold exists. This serializes hold insertion with authorization.
    Reads never fabricate approval or infer permission from a role or model.
    """

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id

    def _check(self, connection: PolicyConnection, intent: PaymentIntent) -> None:
        locked = lock_intent(connection, self.tenant_id, intent.id)
        if terms_of(intent_from_row(locked.intent)) != terms_of(intent):
            raise ScopeDenied("Resource unavailable")

    def approval(self, connection: PolicyConnection, intent: PaymentIntent) -> Approval | None:
        self._check(connection, intent)
        for row in AuthorityStore(connection).for_intent(self.tenant_id, intent.id):
            if terms_of(AuthorityStore.approval(row)) == terms_of(intent):
                return AuthorityStore.approval(row)
        return None

    def mandate(
        self, connection: PolicyConnection, intent: PaymentIntent
    ) -> MandateSnapshot | None:
        self._check(connection, intent)
        row = connection.execute(
            "SELECT * FROM mandates WHERE tenant_id = %s AND account_id = %s "
            "AND delegate_id = %s AND beneficiary_id = %s AND current "
            "AND revoked_at IS NULL FOR UPDATE",
            (self.tenant_id, intent.source_account_id, intent.requested_by, intent.beneficiary_id),
        ).fetchone()
        return AuthorityStore.mandate(row) if row else None

    def hold(self, connection: PolicyConnection, intent: PaymentIntent) -> HoldState:
        self._check(connection, intent)
        rows = connection.execute(
            "SELECT hold_id FROM security_holds WHERE tenant_id = %s AND resource_id = %s "
            "AND state = 'ACTIVE' ORDER BY id FOR UPDATE",
            (self.tenant_id, intent.id),
        ).fetchall()
        return HoldState(held=bool(rows), risk_floor=Tier.T3 if rows else Tier.T0)
