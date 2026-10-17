"""Reset the isolated demo tenant: only Dev C tables, never identities or audit history."""

import argparse

from backend.authz.storage import Database
from backend.config import Settings
from backend.demo.scenarios import ScenarioSpec, scenario
from backend.demo.seed import seed_scenario
from backend.finance.migrations import migrate_all

DEMO_ENVIRONMENTS = frozenset({"development", "test"})
# Child tables first so every delete respects the logical dependencies.
RESETTABLE_TABLES = (
    "untrusted_documents",
    "reconciliation_evidence",
    "reconciliation_cases",
    "university_receipts",
    "sim_provider_faults",
    "sim_provider_transfers",
    "spend_entries",
    "ledger_entries",
    "idempotency_keys",
    "transfers",
    "university_postings",
    "payment_intents",
    "fx_quotes",
    "tuition_obligations",
    "beneficiaries",
    "payment_rules",
    "university_policies",
    "funding_accounts",
)
DEFAULT_SCENARIO = "tuition_happy_path"


def reset_demo_fixture(database: Database, tenant_id: str, scenario_id: str) -> int:
    """Internal backend-only action. Returns the new run number."""
    spec = scenario(scenario_id)
    with database.connection() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"reset:{tenant_id}",))
        # Same order as the executor (account first) so a racing payment cannot deadlock a reset.
        connection.execute(
            "SELECT 1 FROM funding_accounts WHERE tenant_id = %s FOR UPDATE", (tenant_id,)
        )
        for table in RESETTABLE_TABLES:
            connection.execute(f"DELETE FROM {table} WHERE tenant_id = %s", (tenant_id,))  # noqa: S608
        run_no = _next_run(connection, tenant_id, spec)
        seed_scenario(connection, tenant_id, spec)
    return run_no


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset the isolated Rantau demo fixture")
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--migrate", action="store_true", help="apply pending migrations first")
    args = parser.parse_args()
    settings = Settings()
    if settings.app_env not in DEMO_ENVIRONMENTS or not settings.database_url:
        parser.error("Reset runs only in development/test with DATABASE_URL set")
    if not settings.auth_tenant_id:
        parser.error("Configure AUTH_TENANT_ID for the isolated demo tenant")
    database = Database(settings.database_url.get_secret_value())
    if args.migrate:
        migrate_all(database)
    try:
        run_no = reset_demo_fixture(database, settings.auth_tenant_id, args.scenario)
    except ValueError as error:
        parser.error(str(error))
    print(f"Demo tenant reset: scenario={args.scenario} run={run_no}")


def _next_run(connection, tenant_id: str, spec: ScenarioSpec) -> int:  # type: ignore[no-untyped-def]
    row = connection.execute(
        "INSERT INTO demo_state (tenant_id, run_no, scenario_id) VALUES (%s, 1, %s) "
        "ON CONFLICT (tenant_id) DO UPDATE SET run_no = demo_state.run_no + 1, "
        "scenario_id = EXCLUDED.scenario_id, sim_offset_seconds = 0, "
        "reset_at = clock_timestamp() RETURNING run_no",
        (tenant_id, spec.id),
    ).fetchone()
    return int(row["run_no"])


if __name__ == "__main__":
    main()
