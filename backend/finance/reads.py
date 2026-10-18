"""Scoped reads of quotes, intents and transfers (no financial effects except stored quotes)."""

from backend.authz.policy_repository import PolicyConnection
from backend.authz.service import AuthService
from backend.authz.storage import Database
from backend.contracts.enums import Currency, PaymentState, ReasonCode, Role, Tier
from backend.contracts.http import AuditEntry
from backend.contracts.models import (
    ActorContext,
    FundingAccountOption,
    FxQuote,
    PaymentIntentView,
    PaymentOptions,
    PaymentResult,
    PermissionSummary,
    ScopeDenied,
    TrustedBeneficiary,
    UniversityPolicy,
    UntrustedDocument,
)
from backend.finance.quotes import QuoteService
from backend.finance.records import Row, fetch, may_view
from backend.university.port import ObligationReader


class FinanceReads:
    def __init__(
        self,
        database: Database,
        auth: AuthService,
        obligations: ObligationReader,
        quote_service: QuoteService | None = None,
    ) -> None:
        self.database = database
        self.auth = auth
        self.obligations = obligations
        self.quote_service = quote_service or QuoteService()

    def payment_options(self, actor: ActorContext, obligation_alias: str) -> PaymentOptions:
        """Accounts the student may use and the verified university payee, masked."""
        if actor.role != Role.STUDENT:
            raise ScopeDenied("Resource unavailable")
        obligation = self.obligations.get(actor, obligation_alias)
        with self.database.connection() as connection:
            accounts = connection.execute(
                "SELECT alias, owner_id, masked_number FROM funding_accounts "
                "WHERE tenant_id = %s AND active "
                "AND (owner_id = %s OR %s = ANY(permitted_requesters)) "
                "ORDER BY alias",
                (actor.tenant_id, actor.actor_id, actor.actor_id),
            ).fetchall()
            payee = connection.execute(
                "SELECT alias, masked_display FROM beneficiaries WHERE tenant_id = %s "
                "AND owner_id = %s AND purpose_type = 'TUITION' AND verified "
                "ORDER BY alias LIMIT 1",
                (actor.tenant_id, obligation.university_id),
            ).fetchone()
        if payee is None or not accounts:
            raise ScopeDenied("Resource unavailable")
        return PaymentOptions(
            obligation_id=obligation_alias,
            accounts=tuple(
                FundingAccountOption(
                    id=row["alias"],
                    label=row["masked_number"],
                    funded_by_requester=row["owner_id"] == actor.actor_id,
                )
                for row in accounts
            ),
            beneficiary_id=payee["alias"],
            beneficiary_label=payee["masked_display"],
        )

    def quotes(self, actor: ActorContext, obligation_alias: str) -> tuple[FxQuote, ...]:
        balance = self.obligations.get(actor, obligation_alias).balance_minor
        if balance == 0:
            return ()
        with self.database.connection() as connection:
            return self.quote_service.issue(connection, actor.tenant_id, balance)

    def allowance_quotes(self, actor: ActorContext, destination_minor: int) -> tuple[FxQuote, ...]:
        with self.database.connection() as connection:
            self.auth.current_actor(connection, actor)
            return self.quote_service.issue(connection, actor.tenant_id, destination_minor)

    def intent_list(self, actor: ActorContext) -> tuple[PaymentIntentView, ...]:
        with self.database.connection() as connection:
            self.auth.current_actor(connection, actor)
            rows = connection.execute(
                "SELECT * FROM payment_intents WHERE tenant_id = %s "
                "AND (requested_by = %s OR funding_owner_id = %s) ORDER BY created_at DESC",
                (actor.tenant_id, actor.actor_id, actor.actor_id),
            ).fetchall()
            return tuple(self._view(connection, actor, row) for row in rows)

    def documents(self, actor: ActorContext) -> tuple[UntrustedDocument, ...]:
        with self.database.connection() as connection:
            self.auth.current_actor(connection, actor)
            rows = connection.execute(
                "SELECT alias, kind, title, body, claimed_sender, received_at "
                "FROM untrusted_documents WHERE tenant_id = %s AND student_id = %s "
                "ORDER BY received_at DESC",
                (actor.tenant_id, actor.actor_id),
            ).fetchall()
        return tuple(UntrustedDocument(id=row.pop("alias"), **row) for row in rows)

    def intent_view(self, actor: ActorContext, alias: str) -> PaymentIntentView:
        with self.database.connection() as connection:
            row = self._visible_intent(connection, actor, alias)
            return self._view(connection, actor, row)

    def _view(
        self, connection: PolicyConnection, actor: ActorContext, row: Row
    ) -> PaymentIntentView:
        beneficiary = fetch(connection, "beneficiary", actor.tenant_id, row["beneficiary_alias"])
        return PaymentIntentView(
            id=row["alias"],
            purpose=row["purpose"],
            state=PaymentState(row["state"]),
            tier=Tier(row["tier"]),
            obligation_id=row["obligation_alias"],
            source_currency=Currency(row["source_currency"]),
            destination_currency=Currency(row["destination_currency"]),
            source_total_minor=row["source_total_minor"],
            destination_amount_minor=row["destination_amount_minor"],
            quote_id=row["quote_alias"],
            quote_expiry=row["quote_expiry"],
            terms_hash=row["terms_hash"],
            beneficiary_label=beneficiary["masked_display"] if beneficiary else "Unavailable",
            funded_by_requester=row["funding_owner_id"] == actor.actor_id,
            hold_reason=_hold_reason(connection, actor.tenant_id, row),
        )

    def payment_result(self, actor: ActorContext, transfer_alias: str) -> PaymentResult:
        with self.database.connection() as connection:
            transfer = fetch_transfer_row(connection, actor.tenant_id, transfer_alias)
            self._visible_intent(connection, actor, transfer["intent_alias"])
            audit = connection.execute(
                "SELECT audit_event_id FROM audit_events WHERE tenant_id = %s AND resource_id = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (actor.tenant_id, transfer_alias),
            ).fetchone()
            assert audit is not None
            return PaymentResult(
                payment_id=transfer_alias,
                intent_id=transfer["intent_alias"],
                provider_reference=transfer["provider_reference"],
                transfer_status=PaymentState(transfer["state"]),
                receipt_reference=transfer["receipt_reference"],
                audit_event_id=audit["audit_event_id"],
            )

    def payment_for_intent(self, actor: ActorContext, alias: str) -> PaymentResult | None:
        """Recover a submitted outcome after response loss without starting another payment."""
        with self.database.connection() as connection:
            self._visible_intent(connection, actor, alias)
            row = connection.execute(
                "SELECT alias FROM transfers WHERE tenant_id = %s AND intent_alias = %s",
                (actor.tenant_id, alias),
            ).fetchone()
        return self.payment_result(actor, row["alias"]) if row else None

    def beneficiary(self, actor: ActorContext, alias: str) -> TrustedBeneficiary:
        with self.database.connection() as connection:
            self.auth.current_actor(connection, actor)
            row = fetch(connection, "beneficiary", actor.tenant_id, alias)
            if row is None:
                raise ScopeDenied("Resource unavailable")
            return TrustedBeneficiary(
                id=row["alias"],
                owner_id=row["owner_id"],
                masked_display=row["masked_display"],
                fingerprint=row["fingerprint"],
                verified=row["verified"],
            )

    def permissions(self, actor: ActorContext) -> tuple[PermissionSummary, ...]:
        with self.database.connection() as connection:
            self.auth.current_actor(connection, actor)
            rows = connection.execute(
                "SELECT alias, owner_id FROM funding_accounts WHERE tenant_id = %s AND active "
                "AND (owner_id = %s OR %s = ANY(permitted_requesters)) ORDER BY alias",
                (actor.tenant_id, actor.actor_id, actor.actor_id),
            ).fetchall()
        return tuple(
            PermissionSummary(
                account_id=row["alias"],
                owner_id=row["owner_id"],
                permitted_purposes=("TUITION",),
                approval_required=True,
            )
            for row in rows
        )

    def policy(self, actor: ActorContext) -> UniversityPolicy:
        with self.database.connection() as connection:
            self.auth.current_actor(connection, actor)
            row = connection.execute(
                "SELECT p.policy FROM university_policies p JOIN tuition_obligations o "
                "ON o.tenant_id = p.tenant_id AND o.policy_alias = p.alias "
                "WHERE o.tenant_id = %s AND o.student_id = %s ORDER BY o.alias LIMIT 1",
                (actor.tenant_id, actor.actor_id),
            ).fetchone()
        if row is None:
            raise ScopeDenied("Resource unavailable")
        return UniversityPolicy.model_validate(row["policy"])

    def owner_of_intent(self, tenant_id: str, alias: str) -> str | None:
        with self.database.connection() as connection:
            row = fetch(connection, "intent", tenant_id, alias)
            return row["funding_owner_id"] if row else None

    def _visible_intent(self, connection: PolicyConnection, actor: ActorContext, alias: str) -> Row:
        self.auth.current_actor(connection, actor)
        row = fetch(connection, "intent", actor.tenant_id, alias)
        if row is None or not may_view(actor.actor_id, row):
            raise ScopeDenied("Resource unavailable")
        return row


def fetch_transfer_row(connection: PolicyConnection, tenant_id: str, alias: str) -> Row:
    row = connection.execute(
        "SELECT * FROM transfers WHERE tenant_id = %s AND alias = %s", (tenant_id, alias)
    ).fetchone()
    if row is None:
        raise ScopeDenied("Resource unavailable")
    return row


def audit_entries(
    database: Database, auth: AuthService, actor: ActorContext, resource_id: str
) -> tuple[AuditEntry, ...]:
    """Redacted audit rows for a resource the actor may already see."""
    with database.connection() as connection:
        auth.current_actor(connection, actor)
        if not _may_see_resource(connection, actor, resource_id):
            raise ScopeDenied("Resource unavailable")
        rows = connection.execute(
            "SELECT audit_event_id, run_no, action, resource_id, decision, reason_code, created_at "
            "FROM audit_events WHERE tenant_id = %s AND resource_id = %s ORDER BY created_at",
            (actor.tenant_id, resource_id),
        ).fetchall()
    return tuple(AuditEntry(**row) for row in rows)


def _may_see_resource(connection: PolicyConnection, actor: ActorContext, resource_id: str) -> bool:
    tenant = actor.tenant_id
    intent = fetch(connection, "intent", tenant, resource_id)
    if intent is None:
        transfer = connection.execute(
            "SELECT intent_alias FROM transfers WHERE tenant_id = %s AND alias = %s",
            (tenant, resource_id),
        ).fetchone()
        intent = fetch(connection, "intent", tenant, transfer["intent_alias"]) if transfer else None
    if intent is not None:
        return may_view(actor.actor_id, intent)
    case = connection.execute(
        "SELECT o.student_id FROM reconciliation_cases c JOIN tuition_obligations o "
        "ON o.tenant_id = c.tenant_id AND o.alias = c.obligation_alias "
        "WHERE c.tenant_id = %s AND c.alias = %s",
        (tenant, resource_id),
    ).fetchone()
    return bool(case and case["student_id"] == actor.actor_id)


def _hold_reason(connection: PolicyConnection, tenant_id: str, intent: Row) -> ReasonCode | None:
    """Why a request is held, from its latest audited decision; unknown reasons stay hidden."""
    if PaymentState(intent["state"]) != PaymentState.ON_HOLD:
        return None
    latest = connection.execute(
        "SELECT reason_code FROM audit_events WHERE tenant_id = %s AND resource_id = %s "
        "AND reason_code IS NOT NULL ORDER BY created_at DESC LIMIT 1",
        (tenant_id, intent["alias"]),
    ).fetchone()
    try:
        return ReasonCode(latest["reason_code"]) if latest else None
    except ValueError:
        return None
