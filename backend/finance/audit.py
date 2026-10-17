"""Central writer for the append-only audit trail; only allowlisted state fields are stored."""

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from backend.authz.policy_repository import PolicyConnection

SAFE_STATE_KEYS = frozenset(
    {
        "state",
        "tier",
        "decision",
        "reason_code",
        "currency",
        "source_total_minor",
        "destination_amount_minor",
        "policy_decision_id",
    }
)


@dataclass(frozen=True)
class AuditEvent:
    tenant_id: str
    action: str
    resource_type: str
    actor_id: str | None = None
    resource_id: str | None = None
    decision: str | None = None
    reason_code: str | None = None
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    request_id: str | None = None


class AuditWriter:
    def record(self, connection: PolicyConnection, event: AuditEvent) -> str:
        audit_id = f"audit_{uuid4().hex}"
        connection.execute(
            "INSERT INTO audit_events (audit_event_id, tenant_id, run_no, actor_id, action, "
            "resource_type, resource_id, decision, reason_code, before_state, after_state, "
            "request_id) VALUES (%s, %s, "
            "COALESCE((SELECT run_no FROM demo_state WHERE tenant_id = %s), 0), "
            "%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                audit_id,
                event.tenant_id,
                event.tenant_id,
                event.actor_id,
                event.action,
                event.resource_type,
                event.resource_id,
                event.decision,
                event.reason_code,
                _redacted(event.before_state),
                _redacted(event.after_state),
                event.request_id,
            ),
        )
        return audit_id


def _redacted(state: dict[str, Any] | None) -> Jsonb | None:
    if state is None:
        return None
    return Jsonb({key: value for key, value in state.items() if key in SAFE_STATE_KEYS})
