"""Test-only SQL financial handoff. Never imported by application wiring."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from backend.approvals.repository import MandateCandidate
from backend.authz.policy_models import PaymentSnapshot, SpendingEntry
from backend.contracts.authority import ReviewDisplay
from backend.contracts.models import ScopeDenied, TrustedBeneficiary
from backend.contracts.terms import canonical_terms_hash
from tests.authz.policy_data import allowance, tuition


def snapshot_now(*, routine=False, own=False, intent_id="intent_001"):
    snapshot = allowance() if routine else tuition()
    now = datetime.now(UTC)
    expiry = now + timedelta(minutes=15)
    intent = snapshot.intent.model_copy(
        update={
            "id": intent_id,
            "intent_id": intent_id,
            "quote_expiry": expiry,
            "funding_owner_id": "stu_001" if own else "par_001",
        }
    )
    intent = intent.model_copy(update={"terms_hash": canonical_terms_hash(intent)})
    day = now.astimezone(ZoneInfo(snapshot.account.timezone)).date()
    return snapshot.model_copy(
        update={
            "intent": intent,
            "account": snapshot.account.model_copy(
                update={"owner_id": intent.funding_owner_id, "available_minor": 500_000_000}
            ),
            "quote": snapshot.quote.model_copy(update={"expires_at": expiry}),
            "rules": snapshot.rules.model_copy(
                update={
                    "effective_from": now - timedelta(days=1),
                    "effective_to": now + timedelta(days=30),
                }
            ),
            "university_policy": snapshot.university_policy.model_copy(
                update={
                    "effective_from": now - timedelta(days=1),
                    "effective_to": now + timedelta(days=30),
                }
            ),
            "approval": None,
            "mandate": None,
            "spending_day": day,
            "spending_month": day.replace(day=1),
        }
    )


class SQLFinance:
    delay = 0

    def __init__(self, database):
        self.database = database
        with database.connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS test_finance_lock (tenant text PRIMARY KEY)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS test_finance_intent "
                "(id text PRIMARY KEY, data jsonb NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS test_finance_spending "
                "(intent_id text PRIMARY KEY, amount bigint NOT NULL, at timestamptz NOT NULL)"
            )
            connection.execute(
                "TRUNCATE test_finance_lock, test_finance_intent, test_finance_spending"
            )
            connection.execute("INSERT INTO test_finance_lock VALUES ('demo_001')")
        self.put(snapshot_now())

    def put(self, snapshot):
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO test_finance_intent VALUES (%s,%s) "
                "ON CONFLICT (id) DO UPDATE SET data=EXCLUDED.data",
                (snapshot.intent.id, Jsonb(snapshot.model_dump(mode="json"))),
            )

    def load_intent(self, connection, actor, intent_id):
        connection.execute(
            "SELECT tenant FROM test_finance_lock WHERE tenant=%s FOR UPDATE", (actor.tenant_id,)
        )
        row = connection.execute(
            "SELECT data FROM test_finance_intent WHERE id=%s FOR UPDATE", (intent_id,)
        ).fetchone()
        if row is None:
            raise ScopeDenied()
        snapshot = PaymentSnapshot.model_validate(row["data"])
        if actor.tenant_id != snapshot.tenant_id or actor.actor_id not in {
            snapshot.intent.requested_by,
            snapshot.account.owner_id,
        }:
            raise ScopeDenied()
        if self.delay:
            connection.execute("SELECT pg_sleep(%s)", (self.delay,))
        rows = connection.execute("SELECT * FROM test_finance_spending").fetchall()
        spending = tuple(
            SpendingEntry(
                intent_id=row["intent_id"],
                account_id=snapshot.account.id,
                currency=snapshot.account.currency,
                amount_minor=row["amount"],
                state="RESERVED",
                at=row["at"],
            )
            for row in rows
        )
        return snapshot.model_copy(
            update={
                "spending": spending,
                "account": snapshot.account.model_copy(
                    update={
                        "available_minor": snapshot.account.available_minor
                        - sum(e.amount_minor for e in spending)
                    }
                ),
            }
        )

    def load_payment(self, connection, actor, action):
        return self.load_intent(connection, actor, action.resource_id)

    def load_reconciliation(self, connection, actor, action):
        raise ScopeDenied()

    def review_display(self, connection, actor, snapshot):
        return ReviewDisplay(
            source_label="Synthetic IDR ***001",
            beneficiary_label=snapshot.beneficiary.masked_display,
            source_principal_minor=snapshot.quote.source_principal_minor,
            fee_minor=snapshot.quote.fee_minor,
        )

    def set_intent_state(self, connection, actor, intent, state):
        snapshot = self.load_intent(connection, actor, intent.id)
        assert snapshot.intent == intent
        connection.execute(
            "UPDATE test_finance_intent SET data=%s WHERE id=%s",
            (
                Jsonb(
                    snapshot.model_copy(
                        update={"intent": intent.model_copy(update={"state": state})}
                    ).model_dump(mode="json")
                ),
                intent.id,
            ),
        )

    def load_mandate_candidate(self, connection, actor, request):
        connection.execute(
            "SELECT tenant FROM test_finance_lock WHERE tenant=%s FOR UPDATE", (actor.tenant_id,)
        )
        snapshot = snapshot_now(routine=True)
        return MandateCandidate(
            tenant_id=snapshot.tenant_id,
            account=snapshot.account,
            delegate_id="stu_001",
            relationship_verified=True,
            source_label="Synthetic IDR ***001",
            beneficiary=TrustedBeneficiary(
                id=snapshot.intent.beneficiary_id,
                owner_id="stu_001",
                masked_display="Synthetic student ***001",
                verified=True,
                fingerprint=snapshot.intent.beneficiary_fingerprint,
            ),
        )
