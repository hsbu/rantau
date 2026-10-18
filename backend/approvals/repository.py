"""Trusted Dev C handoff, with the same transaction/lock rules as PolicyRepository."""

from typing import Protocol

from backend.authz.policy_models import AccountSnapshot, PaymentSnapshot
from backend.authz.policy_repository import PolicyConnection, PolicyRepository
from backend.contracts.authority import MandateRequest, ReviewDisplay
from backend.contracts.enums import PaymentState
from backend.contracts.models import (
    ActorContext,
    Contract,
    Identifier,
    PaymentIntent,
    TrustedBeneficiary,
)


class MandateCandidate(Contract):
    tenant_id: Identifier
    account: AccountSnapshot
    beneficiary: TrustedBeneficiary
    delegate_id: Identifier
    relationship_verified: bool
    source_label: str


class ApprovalFinanceRepository(PolicyRepository, Protocol):
    """Never install a test implementation in the running application.

    Lock C account then intent/obligation/trust/policy rows before B authority.
    All writers must honor that order. Reads must be current and tenant-scoped.
    load_intent allows only the stored requester or funding owner, using verified
    funding relationships; sponsor visibility never grants student-private data.
    review_display returns masked labels and the exact trusted quote's fee split.
    Quote IDs identify immutable amount/rate/fee/expiry records; repricing must
    create a new quote ID and intent revision, never overwrite an existing quote.
    set_intent_state must CAS the full current terms/revision, raising a typed
    conflict on stale/terminal state, without touching money. Candidate mandate
    relationships must come from trusted storage, never chat or sharing consent.
    """

    def load_intent(
        self, connection: PolicyConnection, actor: ActorContext, intent_id: str
    ) -> PaymentSnapshot: ...

    def review_display(
        self, connection: PolicyConnection, actor: ActorContext, snapshot: PaymentSnapshot
    ) -> ReviewDisplay: ...

    def load_mandate_candidate(
        self, connection: PolicyConnection, actor: ActorContext, request: MandateRequest
    ) -> MandateCandidate: ...

    def set_intent_state(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        intent: PaymentIntent,
        state: PaymentState,
    ) -> None: ...
