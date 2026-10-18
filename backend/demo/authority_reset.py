"""Return Dev B's per-run state to the starting line without deleting any history."""

from typing import Any
from uuid import uuid4

from backend.authz.policy_repository import PolicyConnection

RESET_ACTOR_ID = "demo_reset"
_OPEN_APPROVAL_STATES = ("REQUESTED", "PENDING", "APPROVED")


def close_authority_state(connection: PolicyConnection, tenant_id: str) -> None:
    """Revoke open approvals, mandates and consent; clear holds; resolve open cases.

    Dev B's history tables reject deletes, so each change is a legal state transition that
    leaves an audit event. Identities and login sessions are intentionally untouched.
    """
    _revoke_approvals(connection, tenant_id)
    _revoke_mandates(connection, tenant_id)
    _clear_holds(connection, tenant_id)
    _resolve_cases(connection, tenant_id)
    connection.execute(
        "UPDATE student_sponsor_consents SET revoked_at = clock_timestamp() "
        "WHERE tenant_id = %s AND revoked_at IS NULL",
        (tenant_id,),
    )


def _revoke_approvals(connection: PolicyConnection, tenant_id: str) -> None:
    rows = connection.execute(
        "UPDATE approvals SET state = 'REVOKED' WHERE tenant_id = %s AND state = ANY(%s) "
        "RETURNING approval_id",
        (tenant_id, list(_OPEN_APPROVAL_STATES)),
    ).fetchall()
    for row in rows:
        _authority_event(connection, tenant_id, "APPROVAL_REVOKED", row["approval_id"], "REVOKED")


def _revoke_mandates(connection: PolicyConnection, tenant_id: str) -> None:
    rows = connection.execute(
        "UPDATE mandates SET revoked_at = clock_timestamp() "
        "WHERE tenant_id = %s AND current AND revoked_at IS NULL RETURNING mandate_id",
        (tenant_id,),
    ).fetchall()
    for row in rows:
        _authority_event(connection, tenant_id, "MANDATE_REVOKED", row["mandate_id"], "REVOKED")


def _clear_holds(connection: PolicyConnection, tenant_id: str) -> None:
    rows = connection.execute(
        "SELECT hold_id, resource_id, reason_code FROM security_holds "
        "WHERE tenant_id = %s AND state = 'ACTIVE' FOR UPDATE",
        (tenant_id,),
    ).fetchall()
    for row in rows:
        event_id = _event_id()
        connection.execute(
            "UPDATE security_holds SET state = 'CLEARED', cleared_by = %s, "
            "cleared_at = clock_timestamp(), audit_event_id = %s "
            "WHERE tenant_id = %s AND hold_id = %s",
            (RESET_ACTOR_ID, event_id, tenant_id, row["hold_id"]),
        )
        _security_event(
            connection, tenant_id, event_id, row, "HOLD_CLEARED", "CLEAR_HOLD", "CLEARED"
        )


def _resolve_cases(connection: PolicyConnection, tenant_id: str) -> None:
    rows = connection.execute(
        "SELECT case_id, resource_id, reason_code FROM security_cases "
        "WHERE tenant_id = %s AND state <> 'RESOLVED' FOR UPDATE",
        (tenant_id,),
    ).fetchall()
    for row in rows:
        event_id = _event_id()
        connection.execute(
            "UPDATE security_cases SET state = 'RESOLVED', updated_at = clock_timestamp(), "
            "audit_event_id = %s WHERE tenant_id = %s AND case_id = %s",
            (event_id, tenant_id, row["case_id"]),
        )
        _security_event(
            connection, tenant_id, event_id, row, "CASE_REVIEWED", "RESOLVE_CASE", "RESOLVED"
        )


def _authority_event(
    connection: PolicyConnection, tenant_id: str, action: str, resource_id: str, state: str
) -> None:
    connection.execute(
        "INSERT INTO authority_events (audit_event_id, tenant_id, actor_id, action, resource_id, "
        "state) VALUES (%s, %s, %s, %s, %s, %s)",
        (_event_id(), tenant_id, RESET_ACTOR_ID, action, resource_id, state),
    )


def _security_event(
    connection: PolicyConnection,
    tenant_id: str,
    event_id: str,
    row: dict[str, Any],
    action: str,
    decision: str,
    state: str,
) -> None:
    connection.execute(
        "INSERT INTO security_events (audit_event_id, tenant_id, actor_id, action, decision, "
        "resource_id, reason_code, state) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            event_id,
            tenant_id,
            RESET_ACTOR_ID,
            action,
            decision,
            row["resource_id"],
            row["reason_code"],
            state,
        ),
    )


def _event_id() -> str:
    return "audit_" + uuid4().hex
