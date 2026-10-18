from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest

from backend.authz.policy_models import PaymentSnapshot, ReconciliationSnapshot
from backend.authz.policy_transaction import TransactionAuthorization
from backend.authz.storage import migrate
from backend.contracts.enums import Decision
from backend.contracts.models import ScopeDenied, ServiceUnavailable
from tests.authz.policy_data import ACTION, approve, tuition


def fresh_payment():
    now = datetime.now(UTC)
    snapshot = tuition()
    expiry = now + timedelta(minutes=15)
    snapshot = snapshot.model_copy(
        update={
            "intent": snapshot.intent.model_copy(update={"quote_expiry": expiry}),
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
            "spending_day": now.astimezone(ZoneInfo(snapshot.account.timezone)).date(),
            "spending_month": now.astimezone(ZoneInfo(snapshot.account.timezone))
            .date()
            .replace(day=1),
        }
    )
    return approve(snapshot, expires_at=now + timedelta(minutes=10))


@dataclass
class FinancialRepository:
    payment: PaymentSnapshot = field(default_factory=fresh_payment)
    seen: list = field(default_factory=list)
    delay: float = 0
    error: Exception | None = None

    def load_payment(self, connection, actor, action):
        self.seen.append(connection)
        if self.delay:
            connection.execute("SELECT pg_sleep(%s)", (self.delay,))
        if self.error:
            raise self.error
        return self.payment

    def load_reconciliation(self, connection, actor, action):
        self.seen.append(connection)
        return ReconciliationSnapshot(
            tenant_id=actor.tenant_id,
            case_id=action.resource_id,
            student_id=actor.actor_id,
            submission_allowed=True,
        )


@pytest.fixture
def executor(service):
    with service.database.connection() as connection:
        connection.execute(
            "UPDATE actors SET scopes = scopes || ARRAY['payment:execute','reconciliation:submit'] "
            "WHERE actor_id = 'stu_001'"
        )
    return service.login("student", "a-long-student-test-password", "policy-tests").actor


def events(database):
    with database.connection() as connection:
        return connection.execute("SELECT * FROM policy_decisions").fetchall()


async def test_same_transaction_persists_redacted_audit_only_when_caller_commits(service, executor):
    repository = FinancialRepository()
    with service.database.connection() as connection:
        outcome = await TransactionAuthorization(connection, service, repository).evaluate(
            executor, ACTION
        )
        assert outcome.decision == Decision.ALLOW
        assert repository.seen == [connection]
        assert not events(service.database)  # Adapter did not secretly commit.
        row = connection.execute("SELECT * FROM policy_decisions").fetchone()
        assert row["audit_event_id"] == outcome.audit_event_id
        assert set(row) == {
            "id",
            "audit_event_id",
            "tenant_id",
            "actor_id",
            "action",
            "resource_id",
            "decision",
            "tier",
            "reason_code",
            "created_at",
        }
        assert "acct_idr_01" not in repr(row) and executor.session_id not in repr(row)
    assert len(events(service.database)) == 1


async def test_rollback_leaves_no_durable_audit_or_authorization(service, executor):
    with pytest.raises(RuntimeError, match="caller rollback"):
        with service.database.connection() as connection:
            await TransactionAuthorization(connection, service, FinancialRepository()).evaluate(
                executor, ACTION
            )
            raise RuntimeError("caller rollback")
    assert events(service.database) == []


async def test_denied_financial_attempt_has_durable_reason_and_no_sensitive_snapshot(
    service, executor
):
    repository = FinancialRepository()
    repository.payment = repository.payment.model_copy(update={"held": True})
    with service.database.connection() as connection:
        result = await TransactionAuthorization(connection, service, repository).evaluate(
            executor, ACTION
        )
        assert result.decision == Decision.HOLD
    row = events(service.database)[0]
    assert row["reason_code"] == "SECURITY_HOLD" and row["decision"] == "HOLD"


async def test_revoked_or_forged_current_identity_cannot_reach_repository(service, executor):
    with service.database.connection() as connection:
        connection.execute("UPDATE auth_sessions SET revoked_at = clock_timestamp()")
    repository = FinancialRepository()
    with service.database.connection() as connection:
        with pytest.raises(ScopeDenied):
            await TransactionAuthorization(connection, service, repository).evaluate(
                executor, ACTION
            )
    assert not repository.seen and not events(service.database)


async def test_missing_scope_denies_before_repository_and_redacts_untrusted_resource(
    service, signed_in
):
    repository = FinancialRepository()
    action = ACTION.model_copy(update={"resource_id": "private_caller_supplied_identifier"})
    with service.database.connection() as connection:
        result = await TransactionAuthorization(connection, service, repository).evaluate(
            signed_in.actor, action
        )
    assert result.decision == Decision.DENY and not repository.seen
    assert events(service.database)[0]["resource_id"] is None


async def test_cross_tenant_actor_is_not_accepted_from_caller_context(service, executor):
    with service.database.connection() as connection:
        with pytest.raises(ScopeDenied):
            await TransactionAuthorization(connection, service, FinancialRepository()).evaluate(
                executor.model_copy(update={"tenant_id": "other"}), ACTION
            )
    assert not events(service.database)


async def test_repository_scope_denial_becomes_generic_audited_denial(service, executor):
    repository = FinancialRepository(error=ScopeDenied("private unrelated resource"))
    with service.database.connection() as connection:
        result = await TransactionAuthorization(connection, service, repository).evaluate(
            executor, ACTION
        )
    assert result.decision == Decision.DENY and result.reason_code == "INVALID_SCOPE"
    assert events(service.database)[0]["resource_id"] is None


@pytest.mark.parametrize(
    "error", [ServiceUnavailable("private DSN"), ValueError("private balance")]
)
async def test_repository_failures_are_sanitized_and_never_audited_as_allow(
    service, executor, error
):
    with service.database.connection() as connection:
        with pytest.raises(ServiceUnavailable) as caught:
            await TransactionAuthorization(
                connection, service, FinancialRepository(error=error)
            ).evaluate(executor, ACTION)
        assert "private" not in str(caught.value)
    assert not events(service.database)


async def test_missing_repository_cannot_default_to_fake_authorization(service, executor):
    with service.database.connection() as connection:
        with pytest.raises(ServiceUnavailable):
            await TransactionAuthorization(connection, service, None).evaluate(executor, ACTION)
    assert not events(service.database)


async def test_autocommit_connection_is_rejected_before_any_read(service, executor):
    with psycopg.connect(service.database.dsn, autocommit=True) as connection:
        repository = FinancialRepository()
        with pytest.raises(ServiceUnavailable):
            await TransactionAuthorization(connection, service, repository).evaluate(
                executor, ACTION
            )
        assert not repository.seen


async def test_fresh_database_clock_after_locked_load_expires_quote(service, executor):
    repository = FinancialRepository(delay=0.2)
    expiry = datetime.now(UTC) + timedelta(milliseconds=100)
    snapshot = repository.payment
    repository.payment = approve(
        snapshot.model_copy(
            update={
                "intent": snapshot.intent.model_copy(update={"quote_expiry": expiry}),
                "quote": snapshot.quote.model_copy(update={"expires_at": expiry}),
            }
        )
    )
    with service.database.connection() as connection:
        result = await TransactionAuthorization(connection, service, repository).evaluate(
            executor, ACTION
        )
    assert result.decision == Decision.DENY and result.reason_code == "QUOTE_EXPIRED"


async def test_session_expiry_uses_wall_clock_even_in_an_old_transaction(service, executor):
    with service.database.connection() as connection:
        connection.execute(
            "UPDATE auth_sessions SET expires_at = clock_timestamp() + interval '100 milliseconds'"
        )
    with service.database.connection() as connection:
        with pytest.raises(ScopeDenied):
            await TransactionAuthorization(
                connection, service, FinancialRepository(delay=0.2)
            ).evaluate(executor, ACTION)
    assert not events(service.database)


async def test_audit_insert_failure_never_returns_allow(service, executor):
    # Roll back the disposable schema change with the failed authorization.
    with pytest.raises(ServiceUnavailable):
        with service.database.connection() as connection:
            connection.execute("DROP TABLE policy_decisions")
            await TransactionAuthorization(connection, service, FinancialRepository()).evaluate(
                executor, ACTION
            )
    assert not events(service.database)


async def test_reconciliation_submission_uses_current_identity_and_decision_audit(
    service, executor
):
    action = ACTION.model_copy(
        update={"action": "SUBMIT_RECONCILIATION", "resource_id": "case_001"}
    )
    with service.database.connection() as connection:
        result = await TransactionAuthorization(
            connection, service, FinancialRepository()
        ).evaluate(executor, action)
    assert result.decision == Decision.ALLOW
    assert events(service.database)[0]["action"] == "SUBMIT_RECONCILIATION"


def test_ordered_migrations_replay_and_validate_checksums(database):
    migrate(database)
    with database.connection() as connection:
        rows = connection.execute(
            "SELECT version FROM rantau_migrations ORDER BY version"
        ).fetchall()
        assert [row["version"] for row in rows] == [
            "001_auth",
            "002_policy_audit",
            "003_authority",
            "004_security_cases",
            "005_security_history_guards",
        ]
        connection.execute(
            "UPDATE rantau_migrations SET checksum = 'bad' WHERE version = '002_policy_audit'"
        )
    try:
        with pytest.raises(ValueError, match="checksum"):
            migrate(database)
    finally:
        # Remove only the isolated test cluster's affected migration/table.
        with database.connection() as connection:
            connection.execute("DROP TABLE policy_decisions")
            connection.execute("DELETE FROM rantau_migrations WHERE version = '002_policy_audit'")
        migrate(database)


def test_demo_bootstrap_grants_explicit_gate_entry_scopes(database):
    from backend.authz.bootstrap import provision_demo

    provision_demo(database, "synthetic-student-password", "synthetic-sponsor-password", "test")
    with database.connection() as connection:
        rows = connection.execute("SELECT actor_id, scopes FROM actors").fetchall()
    scopes = {row["actor_id"]: set(row["scopes"]) for row in rows}
    assert {"payment:execute", "reconciliation:submit"} <= scopes["stu_001"]
    assert "payment:execute" in scopes["par_001"]
    assert "sponsor:approve" not in scopes["stu_001"]
