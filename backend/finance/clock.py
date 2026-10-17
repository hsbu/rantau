"""The security clock is the database clock; it must never be shifted by the simulation."""

from datetime import datetime
from zoneinfo import ZoneInfo

from backend.authz.policy_repository import PolicyConnection


def db_now(connection: PolicyConnection) -> datetime:
    row = connection.execute("SELECT clock_timestamp() AS now").fetchone()
    assert row is not None
    now: datetime = row["now"]
    return now


def period_starts(now: datetime, timezone: str) -> tuple[datetime, datetime]:
    """Start of the account-local day and month, as aware datetimes."""
    day_start = now.astimezone(ZoneInfo(timezone)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return day_start, day_start.replace(day=1)
