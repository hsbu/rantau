"""Simulated time for the provider and university only; never used for security decisions."""

from datetime import datetime, timedelta

from backend.authz.policy_repository import PolicyConnection
from backend.finance.clock import db_now


def sim_now(connection: PolicyConnection, tenant_id: str) -> datetime:
    row = connection.execute(
        "SELECT sim_offset_seconds FROM demo_state WHERE tenant_id = %s", (tenant_id,)
    ).fetchone()
    offset = int(row["sim_offset_seconds"]) if row else 0
    return db_now(connection) + timedelta(seconds=offset)


def advance_sim_clock(connection: PolicyConnection, tenant_id: str, seconds: int) -> None:
    if seconds <= 0:
        raise ValueError("The simulated clock only moves forward")
    updated = connection.execute(
        "UPDATE demo_state SET sim_offset_seconds = sim_offset_seconds + %s WHERE tenant_id = %s",
        (seconds, tenant_id),
    )
    if updated.rowcount != 1:
        raise ValueError("No demo run exists for this tenant")
