"""Dev C's trusted financial read boundary for the deterministic policy gate."""

from typing import Any, Protocol

import psycopg

from backend.authz.policy_models import PaymentSnapshot, ReconciliationSnapshot
from backend.contracts.models import ActionIntent, ActorContext

PolicyConnection = psycopg.Connection[dict[str, Any]]


class PolicyRepository(Protocol):
    """Implement using the supplied transaction; never open a separate connection.

    Resolve resource aliases inside actor.tenant_id and enforce stored funding
    relationships. Sharing consent alone cannot authorize a funding request.
    Load all facts from trusted simulator/B-03/B-05 storage, never chat/model data.

    For execution, serialize account spending and intent/quote/beneficiary/policy,
    mandate/approval, owner activation and hold changes under a consistent lock
    order. Writers must use that same locking protocol (including new holds).
    Return complete day/month accounting plus all outstanding reservations; set
    coverage dates in the source account's IANA timezone. Account.available_minor
    excludes ALL reservations. SpendingEntry is one latest charge per intent;
    released/reversed entries are excluded and completed amounts are not counted
    again as reservations. A current intent's reserve must match its exact terms.

    Lock the tuition obligation across all candidate intents. Detect every other
    same-obligation transfer still processing, outcome-unknown or awaiting verified
    posting; never present an apparently UNPAID/PARTIALLY_POSTED obligation as
    ready while one is unresolved. Establish original provider finality and
    verified posting before a recovery top-up. If this cannot be established,
    raise ServiceUnavailable rather than fabricate a ready financial snapshot.
    Known pending obligation states are independently held by the policy engine.

    Stage CREATE_INTENT as an immutable, scoped draft before evaluation. Raise
    ScopeDenied for inaccessible resources, ServiceUnavailable for missing data.
    B-03 records authenticated approvals/mandates; shape validation is no proof.
    No test repository may be used in integrated/non-test application wiring.
    """

    def load_payment(
        self, connection: PolicyConnection, actor: ActorContext, action: ActionIntent
    ) -> PaymentSnapshot: ...

    def load_reconciliation(
        self, connection: PolicyConnection, actor: ActorContext, action: ActionIntent
    ) -> ReconciliationSnapshot:
        """Check case/payment/obligation linkage; allow evidence submission only."""
        ...
