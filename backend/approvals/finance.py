"""C's existing SQL schema implements B's trusted, transaction-bound handoff."""

from backend.approvals.finance_authority import StoredAuthority
from backend.approvals.repository import MandateCandidate
from backend.approvals.service import ApprovalConflict
from backend.approvals.store import terms_of
from backend.authz.policy_models import PaymentSnapshot
from backend.authz.policy_repository import PolicyConnection
from backend.authz.service import AuthService
from backend.contracts.authority import MandateRequest, ReviewDisplay
from backend.contracts.enums import PaymentState
from backend.contracts.models import ActionIntent, ActorContext, PaymentIntent, ScopeDenied
from backend.finance.policy_repo import FinancePolicyRepository, _beneficiary
from backend.finance.records import fetch, intent_from_row, lock_intent, may_view
from backend.finance.states import INTENT_TRANSITIONS, InvalidTransition, require_transition


class FinanceApprovalRepository(FinancePolicyRepository):
    def __init__(self, auth: AuthService) -> None:
        super().__init__(StoredAuthority(auth.tenant_id))
        self.auth = auth

    def load_payment(
        self, connection: PolicyConnection, actor: ActorContext, action: ActionIntent
    ) -> PaymentSnapshot:
        self.auth.current_actor(connection, actor)
        locked = lock_intent(connection, actor.tenant_id, action.resource_id)
        if not may_view(actor.actor_id, locked.intent) or actor.actor_id not in {
            locked.account["owner_id"],
            *locked.account["permitted_requesters"],
        }:
            raise ScopeDenied("Resource unavailable")
        # Freeze all trusted mutable facts before B's authority/security rows.
        fetch(
            connection,
            "beneficiary",
            actor.tenant_id,
            locked.intent["beneficiary_alias"],
            lock="FOR SHARE",
        )
        fetch(connection, "quote", actor.tenant_id, locked.intent["quote_alias"], lock="FOR SHARE")
        connection.execute(
            "SELECT id FROM payment_rules WHERE tenant_id = %s AND version = %s FOR SHARE",
            (actor.tenant_id, locked.intent["policy_version"]),
        ).fetchall()
        if locked.obligation is not None:
            connection.execute(
                "SELECT id FROM university_policies WHERE tenant_id = %s AND alias = %s FOR SHARE",
                (actor.tenant_id, locked.obligation["policy_alias"]),
            ).fetchall()
        connection.execute(
            "SELECT id FROM actors WHERE tenant_id = %s AND actor_id = %s FOR SHARE",
            (actor.tenant_id, locked.account["owner_id"]),
        ).fetchall()
        return super().load_payment(connection, actor, action)

    def load_intent(
        self, connection: PolicyConnection, actor: ActorContext, intent_id: str
    ) -> PaymentSnapshot:
        return self.load_payment(
            connection,
            actor,
            ActionIntent(action="CREATE_INTENT", resource_id=intent_id, terms_hash="lookup"),
        )

    def review_display(
        self, connection: PolicyConnection, actor: ActorContext, snapshot: PaymentSnapshot
    ) -> ReviewDisplay:
        account = fetch(connection, "account", actor.tenant_id, snapshot.account.id)
        quote = fetch(connection, "quote", actor.tenant_id, snapshot.quote.id)
        if account is None or quote is None:
            raise ScopeDenied("Resource unavailable")
        return ReviewDisplay(
            source_label=f"Simulated {account['currency']} account {account['masked_number']}",
            beneficiary_label=snapshot.beneficiary.masked_display,
            source_principal_minor=quote["source_principal_minor"],
            fee_minor=quote["fee_minor"],
        )

    def load_mandate_candidate(
        self, connection: PolicyConnection, actor: ActorContext, request: MandateRequest
    ) -> MandateCandidate:
        self.auth.current_actor(connection, actor)
        account = fetch(
            connection, "account", actor.tenant_id, request.source_account_id, lock="FOR UPDATE"
        )
        if account is None or account["owner_id"] != actor.actor_id:
            raise ScopeDenied("Resource unavailable")
        beneficiary = fetch(
            connection, "beneficiary", actor.tenant_id, request.beneficiary_id, lock="FOR SHARE"
        )
        if beneficiary is None or request.delegate_id not in account["permitted_requesters"]:
            raise ScopeDenied("Resource unavailable")
        return MandateCandidate(
            tenant_id=actor.tenant_id,
            account=self._account(connection, actor.tenant_id, account),
            beneficiary=_beneficiary(beneficiary),
            delegate_id=request.delegate_id,
            relationship_verified=True,
            source_label=f"Simulated {account['currency']} account {account['masked_number']}",
        )

    def set_intent_state(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        intent: PaymentIntent,
        state: PaymentState,
    ) -> None:
        locked = lock_intent(connection, actor.tenant_id, intent.id)
        current = intent_from_row(locked.intent)
        if not may_view(actor.actor_id, locked.intent):
            raise ScopeDenied("Resource unavailable")
        if terms_of(current) != terms_of(intent):
            raise ApprovalConflict("APPROVAL_TERMS_MISMATCH")
        if current.state == state:
            return
        try:
            require_transition(INTENT_TRANSITIONS, current.state, state)
        except InvalidTransition:
            raise ApprovalConflict("AUTHORITY_NOT_CURRENT") from None
        changed = connection.execute(
            "UPDATE payment_intents SET state = %s, version = version + 1 "
            "WHERE id = %s AND state = %s AND version = %s",
            (state.value, locked.intent["id"], current.state.value, locked.intent["version"]),
        )
        if changed.rowcount != 1:
            raise ApprovalConflict("AUTHORITY_NOT_CURRENT")
