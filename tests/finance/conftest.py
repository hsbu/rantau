from dataclasses import dataclass

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from backend.authz.passwords import hash_password
from backend.authz.policy_transaction import TransactionAuthorization
from backend.authz.service import AuthService
from backend.authz.storage import Database
from backend.contracts.models import ActorContext
from backend.demo.reset import reset_demo_fixture
from backend.finance.executor import ExecutionService
from backend.finance.intents import IntentService
from backend.finance.migrations import migrate_all
from backend.finance.policy_repo import FinancePolicyRepository
from backend.finance.provider import SimulatedProvider
from backend.finance.transfers import TransferService
from backend.university.receipts import UniversityReceipts
from backend.university.reconciliation import CaseService, ReviewService
from tests.authz import conftest as auth_conftest
from tests.finance.authority import ScriptedAuthority

# Reuse the auth suite's PostgreSQL cluster fixture without editing its owner's file.
postgres_dsn = auth_conftest.postgres_dsn

TENANT = "demo_001"
FINANCE_DB = "rantau_test_finance"
ACTORS = (
    (
        "stu_001",
        "STUDENT",
        ["student:read", "payment:propose", "payment:execute", "reconciliation:submit"],
    ),
    ("par_001", "SPONSOR", ["sponsor:read", "sponsor:approve", "payment:execute"]),
)
TRUNCATED = (
    "approvals, mandates, authority_events, security_holds, security_cases, security_events, "
    "audit_events, policy_decisions, auth_login_attempts, reconciliation_evidence, "
    "reconciliation_cases, university_receipts, sim_provider_faults, sim_provider_transfers, "
    "spend_entries, ledger_entries, "
    "idempotency_keys, transfers, payment_intents, fx_quotes, university_postings, "
    "tuition_obligations, beneficiaries, payment_rules, university_policies, funding_accounts, "
    "demo_state, actors"
)


@pytest.fixture(scope="session")
def finance_dsn(postgres_dsn):
    """A database separate from the auth tests, which drop and recreate their own tables."""
    with psycopg.connect(postgres_dsn, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {FINANCE_DB} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {FINANCE_DB}")
    dsn = make_conninfo(postgres_dsn, dbname=FINANCE_DB)
    migrate_all(Database(dsn))
    return dsn


@pytest.fixture
def finance_db(finance_dsn):
    database = Database(finance_dsn)
    with database.connection() as connection:
        connection.execute(f"TRUNCATE {TRUNCATED} CASCADE")
        for actor_id, role, scopes in ACTORS:
            connection.execute(
                "INSERT INTO actors (tenant_id, actor_id, role, scopes) VALUES (%s, %s, %s, %s)",
                (TENANT, actor_id, role, scopes),
            )
    return database


@pytest.fixture
def seeded(finance_db):
    reset_demo_fixture(finance_db, TENANT, "tuition_happy_path")
    return finance_db


PASSWORD = "a-long-finance-test-password"
USERNAMES = {"stu_001": "student", "par_001": "sponsor"}


@pytest.fixture(scope="session")
def password_hash():
    return hash_password(PASSWORD)


@dataclass
class Services:
    database: object
    auth: AuthService
    authority: ScriptedAuthority
    intents: IntentService
    executor: ExecutionService
    transfers: TransferService
    cases: CaseService
    review: ReviewService

    def actor(self, actor_id: str) -> ActorContext:
        return self.auth.login(USERNAMES[actor_id], PASSWORD, "finance-tests").actor


@pytest.fixture
def services(seeded, password_hash):
    with seeded.connection() as connection:
        for actor_id, username in USERNAMES.items():
            connection.execute(
                "INSERT INTO auth_credentials (tenant_id, actor_id, username, password_hash) "
                "VALUES (%s, %s, %s, %s)",
                (TENANT, actor_id, username, password_hash),
            )
    auth = AuthService(seeded, TENANT)
    authority = ScriptedAuthority()
    repository = FinancePolicyRepository(authority)

    def gate(connection):
        return TransactionAuthorization(connection, auth, repository)

    transfers = TransferService(seeded, SimulatedProvider(seeded), UniversityReceipts())
    return Services(
        seeded,
        auth,
        authority,
        IntentService(seeded, gate),
        ExecutionService(seeded, gate, transfers),
        transfers,
        CaseService(seeded, gate),
        ReviewService(seeded),
    )


@pytest.fixture
def student(services):
    return services.actor("stu_001")


@pytest.fixture
def sponsor(services):
    return services.actor("par_001")
