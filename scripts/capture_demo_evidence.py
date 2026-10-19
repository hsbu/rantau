"""Save read-only, allowlisted current-run evidence locally for deliverable 06."""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.agent.run_records import RunRecord
from backend.authz.storage import Database
from backend.config import Settings
from backend.demo.reset import DEMO_ENVIRONMENTS

ROOT = Path(__file__).resolve().parent.parent
LIMIT = 256


def application_digest() -> str:
    paths = (
        subprocess.check_output(
            [
                "git",
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                "backend",
                "frontend/app",
                "frontend/lib",
            ],
            cwd=ROOT,
        )
        .decode()
        .split("\0")
    )
    digest = hashlib.sha256()
    for name in sorted(set(paths) - {""}):
        path = ROOT / name
        if path.is_file():
            digest.update(name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def capture(database: Database, tenant: str) -> dict[str, Any]:
    with database.connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        state = c.execute(
            "SELECT scenario_id,run_no FROM demo_state WHERE tenant_id=%s", (tenant,)
        ).fetchone()
        if state is None:
            raise ValueError("No initialized demo run")
        report: dict[str, Any] = {"scenario": state, "simulated": True}
        # Only synthetic current domain records; never auth tables or document prose.
        queries = {
            "accounts": "SELECT alias,owner_id,balance_minor,currency FROM funding_accounts "
            "WHERE tenant_id=%s",
            "intents": "SELECT alias,state,funding_owner_id,source_total_minor,"
            "destination_amount_minor,terms_hash,intent_revision FROM payment_intents "
            "WHERE tenant_id=%s",
            "transfers": "SELECT alias,intent_alias,obligation_alias,state,source_total_minor,"
            "delivered_destination_minor FROM transfers WHERE tenant_id=%s",
            "spending": "SELECT intent_alias,amount_minor,state FROM spend_entries "
            "WHERE tenant_id=%s",
            "ledger": "SELECT transfer_alias,leg,amount_minor,currency FROM ledger_entries "
            "WHERE tenant_id=%s",
            "postings": "SELECT alias,transfer_alias,obligation_alias,posted_minor,kind "
            "FROM university_postings WHERE tenant_id=%s",
            "cases": "SELECT alias,transfer_alias,obligation_alias,state "
            "FROM reconciliation_cases WHERE tenant_id=%s",
        }
        for name, sql in queries.items():
            rows = c.execute(sql + " LIMIT %s", (tenant, LIMIT + 1)).fetchall()
            if len(rows) > LIMIT:
                raise ValueError("Evidence bound exceeded; select a smaller isolated run")
            report[name] = rows
        report["financial_audit"] = c.execute(
            "SELECT audit_event_id,action,resource_type,resource_id,decision,reason_code,"
            "created_at "
            "FROM audit_events WHERE tenant_id=%s AND run_no=%s ORDER BY created_at LIMIT %s",
            (tenant, state["run_no"], LIMIT + 1),
        ).fetchall()
        runs = c.execute(
            "SELECT run_id,metadata,created_at FROM agent_runs WHERE tenant_id=%s "
            "AND scenario_run_no=%s ORDER BY created_at LIMIT %s",
            (tenant, state["run_no"], LIMIT + 1),
        ).fetchall()
        for run in runs:
            RunRecord.model_validate(run["metadata"])
        if len(runs) > LIMIT or len(report["financial_audit"]) > LIMIT:
            raise ValueError("Evidence bound exceeded; select a smaller isolated run")
        report["agent_runs"] = runs
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="New JSON file under .generated/acceptance/"
    )
    args = parser.parse_args()
    settings = Settings()
    if settings.app_env not in DEMO_ENVIRONMENTS or not settings.database_url:
        parser.error("An explicitly configured development/test database is required")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".generated" / "acceptance") or output.suffix != ".json":
        parser.error("Output must be a JSON file under .generated/acceptance/")
    if output.exists():
        parser.error("Use a new filename to preserve earlier evidence")
    report = capture(Database(settings.database_url.get_secret_value()), settings.auth_tenant_id)
    report.update(
        {
            "captured_at": datetime.now(UTC).isoformat(),
            "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT)
            .decode()
            .strip(),
            "application_source_sha256": application_digest(),
            "model": settings.openrouter_model,
            "evidence_level": "SQL and persisted tool diagnostics; browser proof is separate",
            "review": "Unreviewed local evidence; redact and review before any submission",
        }
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, default=str, indent=2) + "\n", encoding="utf-8")
    print("Saved local synthetic-run evidence:", output)


if __name__ == "__main__":
    main()
