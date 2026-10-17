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
from backend.university.obligations import derive_obligation_state


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
        if intent.purpose != "TUITION" or locked.obligation is None:
            raise ServiceUnavailable("Only tuition payments are supported")
        now = db_now(connection)
        account = self._account(connection, tenant, locked.account)
        hold = self.authority.hold(connection, intent)
        beneficiary_row = _required(fetch(connection, "beneficiary", tenant, intent.beneficiary_id))
        quote_row = _required(fetch(connection, "quote", tenant, intent.quote_id))
        obligation = self._obligation(connection, tenant, locked.obligation)
        local_today = now.astimezone(ZoneInfo(account.timezone)).date()
        return PaymentSnapshot(
            tenant_id=tenant,
            intent=intent,
            account=account,
            authorized_requesters=frozenset({intent.requested_by, intent.funding_owner_id}),
            beneficiary=_beneficiary(beneficiary_row),
            recipient_owner_id=obligation.university_id,
            quote=quote_from_row(quote_row),
            rules=self._rules(connection, tenant, intent.policy_version),
            spending=self._spending(connection, tenant, account, now),
            mandate=self.authority.mandate(connection, intent),
            approval=self.authority.approval(connection, intent),
            held=hold.held,
            risk_floor=hold.risk_floor,
            obligation=obligation,
            university_policy=self._university_policy(connection, tenant, obligation),
            spending_day=local_today,
            spending_month=local_today.replace(day=1),
        )

    def load_reconciliation(
        self, connection: PolicyConnection, actor: ActorContext, action: ActionIntent
    ) -> ReconciliationSnapshot:
        raise ServiceUnavailable("Reconciliation snapshots arrive with the university service")

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
        posted = connection.execute(
            "SELECT COALESCE(sum(posted_minor), 0) AS posted FROM university_postings "
            "WHERE tenant_id = %s AND obligation_alias = %s",
            (tenant, row["alias"]),
        ).fetchone()
        unresolved = connection.execute(
            "SELECT 1 FROM transfers WHERE tenant_id = %s AND obligation_alias = %s "
            "AND blocks_obligation",
            (tenant, row["alias"]),
        ).fetchone()
        posted_minor = int(posted["posted"]) if posted else 0
        due = row["amount_due_minor"]
        return TuitionObligation(
            id=row["alias"],
            student_id=row["student_id"],
            university_id=row["university_id"],
            amount_due_minor=due,
            posted_minor=posted_minor,
            balance_minor=due - posted_minor,
            due_at=row["due_at"],
            policy_id=row["policy_alias"],
            state=derive_obligation_state(
                due, posted_minor, unresolved_transfer=unresolved is not None
            ),
        )

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
