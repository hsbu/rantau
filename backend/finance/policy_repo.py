"""Trusted financial snapshots for Dev B's deterministic gate (implements PolicyRepository)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from backend.authz.policy_models import (
    AccountSnapshot,
    PaymentSnapshot,
    PolicyRules,
    ReconciliationSnapshot,
    SpendingEntry,
)
from backend.authz.policy_repository import PolicyConnection
from backend.contracts.enums import Currency
from backend.contracts.models import (
    ActionIntent,
    ActorContext,
    ScopeDenied,
    ServiceUnavailable,
    TrustedBeneficiary,
    TuitionObligation,
    UniversityPolicy,
)
from backend.finance.authority import AuthoritySource
from backend.finance.clock import db_now, period_starts
from backend.finance.quotes import quote_from_row
from backend.finance.records import Row, fetch, intent_from_row, lock_intent, may_view
from backend.finance.simclock import sim_now
from backend.university.obligations import read_obligation

SUBMITTABLE_CASE_STATES = frozenset({"OPEN", "EVIDENCE_REQUIRED", "READY", "NEEDS_INFO"})


class FinancePolicyRepository:
    def __init__(self, authority: AuthoritySource) -> None:
        self.authority = authority

    def load_payment(
        self, connection: PolicyConnection, actor: ActorContext, action: ActionIntent
    ) -> PaymentSnapshot:
        tenant = actor.tenant_id
        locked = lock_intent(connection, tenant, action.resource_id)
        if not may_view(actor.actor_id, locked.intent):
            raise ScopeDenied("Resource unavailable")
        intent = intent_from_row(locked.intent)
        if (intent.purpose == "TUITION") != (locked.obligation is not None):
            raise ServiceUnavailable("Intent purpose and obligation disagree")
        now = db_now(connection)
        account = self._account(connection, tenant, locked.account)
        hold = self.authority.hold(connection, intent)
        beneficiary_row = _required(fetch(connection, "beneficiary", tenant, intent.beneficiary_id))
        quote_row = _required(fetch(connection, "quote", tenant, intent.quote_id))
        obligation = (
            self._obligation(connection, tenant, locked.obligation)
            if locked.obligation is not None
            else None
        )
        # Read last: the gate compares these markers with its own, later clock reading.
        local_today = db_now(connection).astimezone(ZoneInfo(account.timezone)).date()
        return PaymentSnapshot(
            tenant_id=tenant,
            intent=intent,
            account=account,
            authorized_requesters=frozenset({intent.requested_by, intent.funding_owner_id}),
            beneficiary=_beneficiary(beneficiary_row),
            recipient_owner_id=obligation.university_id
            if obligation
            else beneficiary_row["owner_id"],
            quote=quote_from_row(quote_row),
            rules=self._rules(connection, tenant, intent.policy_version),
            spending=self._spending(connection, tenant, account, now),
            mandate=self.authority.mandate(connection, intent),
            approval=self.authority.approval(connection, intent),
            held=hold.held,
            risk_floor=hold.risk_floor,
            obligation=obligation,
            university_policy=(
                self._university_policy(connection, tenant, obligation) if obligation else None
            ),
            spending_day=local_today,
            spending_month=local_today.replace(day=1),
        )

    def load_reconciliation(
        self, connection: PolicyConnection, actor: ActorContext, action: ActionIntent
    ) -> ReconciliationSnapshot:
        case = connection.execute(
            "SELECT c.alias, c.state, o.student_id FROM reconciliation_cases c "
            "JOIN tuition_obligations o ON o.tenant_id = c.tenant_id "
            "AND o.alias = c.obligation_alias WHERE c.tenant_id = %s AND c.alias = %s",
            (actor.tenant_id, action.resource_id),
        ).fetchone()
        if case is None:
            raise ScopeDenied("Resource unavailable")
        return ReconciliationSnapshot(
            tenant_id=actor.tenant_id,
            case_id=case["alias"],
            student_id=case["student_id"],
            submission_allowed=case["state"] in SUBMITTABLE_CASE_STATES,
        )

    def _account(self, connection: PolicyConnection, tenant: str, row: Row) -> AccountSnapshot:
        owner = connection.execute(
            "SELECT active FROM actors WHERE tenant_id = %s AND actor_id = %s",
            (tenant, row["owner_id"]),
        ).fetchone()
        return AccountSnapshot(
            id=row["alias"],
            tenant_id=tenant,
            owner_id=row["owner_id"],
            active=row["active"],
            owner_active=bool(owner and owner["active"]),
            currency=Currency(row["currency"]),
            timezone=row["timezone"],
            available_minor=row["balance_minor"],
            per_transfer_limit_minor=row["per_transfer_limit_minor"],
            daily_limit_minor=row["daily_limit_minor"],
            monthly_limit_minor=row["monthly_limit_minor"],
        )

    def _obligation(self, connection: PolicyConnection, tenant: str, row: Row) -> TuitionObligation:
        return read_obligation(connection, tenant, row, sim_now(connection, tenant)).obligation

    def _rules(self, connection: PolicyConnection, tenant: str, version: str) -> PolicyRules:
        row = connection.execute(
            "SELECT * FROM payment_rules WHERE tenant_id = %s AND version = %s", (tenant, version)
        ).fetchone()
        row = _required(row)
        return PolicyRules(
            version=row["version"],
            effective_from=row["effective_from"],
            effective_to=row["effective_to"],
            routine_threshold_minor=row["routine_threshold_minor"],
            purposes=frozenset(row["purposes"]),
            currency_pairs=frozenset((Currency(a), Currency(b)) for a, b in row["currency_pairs"]),
        )

    def _spending(
        self, connection: PolicyConnection, tenant: str, account: AccountSnapshot, now: datetime
    ) -> tuple[SpendingEntry, ...]:
        _, month_start = period_starts(now, account.timezone)
        rows = connection.execute(
            "SELECT intent_alias, amount_minor, currency, at FROM spend_entries "
            "WHERE tenant_id = %s AND account_alias = %s AND state = 'COMPLETED' AND at >= %s",
            (tenant, account.id, month_start),
        ).fetchall()
        return tuple(
            SpendingEntry(
                intent_id=row["intent_alias"],
                account_id=account.id,
                currency=Currency(row["currency"]),
                amount_minor=row["amount_minor"],
                state="COMPLETED",
                at=row["at"],
            )
            for row in rows
        )

    def _university_policy(
        self, connection: PolicyConnection, tenant: str, obligation: TuitionObligation
    ) -> UniversityPolicy | None:
        row = connection.execute(
            "SELECT policy FROM university_policies WHERE tenant_id = %s AND alias = %s",
            (tenant, obligation.policy_id),
        ).fetchone()
        return UniversityPolicy.model_validate(row["policy"]) if row else None


def _beneficiary(row: Row) -> TrustedBeneficiary:
    return TrustedBeneficiary(
        id=row["alias"],
        owner_id=row["owner_id"],
        masked_display=row["masked_display"],
        fingerprint=row["fingerprint"],
        verified=row["verified"],
    )


def _required(row: Row | None) -> Row:
    if row is None:
        raise ServiceUnavailable("Trusted financial data unavailable")
    return row
