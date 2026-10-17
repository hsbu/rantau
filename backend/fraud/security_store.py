"""PostgreSQL security storage on the caller's protected transaction."""

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from psycopg.pq import TransactionStatus

from backend.authz.policy_repository import PolicyConnection
from backend.contracts.enums import Role
from backend.contracts.models import ActorContext, ScopeDenied, ServiceUnavailable
from backend.fraud.security_cases import (
    SecurityCase,
    SecurityCaseDecision,
    SecurityCaseState,
    SecurityDecision,
    SecurityEventAction,
    SecurityHold,
    SecurityReason,
    SecurityResourceAccess,
)

Record = dict[str, Any]

_CASE_TRANSITIONS: dict[SecurityCaseState, frozenset[SecurityCaseDecision]] = {
    SecurityCaseState.OPEN: frozenset(SecurityCaseDecision),
    SecurityCaseState.UNDER_REVIEW: frozenset(
        {SecurityCaseDecision.RESOLVED, SecurityCaseDecision.ESCALATED}
    ),
    SecurityCaseState.ESCALATED: frozenset(
        {SecurityCaseDecision.UNDER_REVIEW, SecurityCaseDecision.RESOLVED}
    ),
    SecurityCaseState.RESOLVED: frozenset(),
}


class SecurityCaseConflict(Exception):
    """A case changed or reached a terminal state before the requested decision."""


class SecurityStore:
    def __init__(self, resource_access: SecurityResourceAccess) -> None:
        self.resource_access = resource_access

    @staticmethod
    def _require_transaction(connection: PolicyConnection) -> None:
        if (
            connection.autocommit
            or connection.closed
            or connection.info.transaction_status != TransactionStatus.INTRANS
        ):
            raise ServiceUnavailable("Security transaction unavailable")

    @staticmethod
    def _event_id() -> str:
        return "audit_" + uuid4().hex

    def _append_event(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        action: SecurityEventAction,
        decision: SecurityDecision,
        resource_id: str,
        reason: SecurityReason,
        state: str,
        event_id: str,
    ) -> None:
        connection.execute(
            "INSERT INTO security_events "
            "(audit_event_id,tenant_id,actor_id,action,decision,resource_id,reason_code,state) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                event_id,
                actor.tenant_id,
                actor.actor_id,
                action.value,
                decision.value,
                resource_id,
                reason.value,
                state,
            ),
        )

    def assert_resource_access(
        self, connection: PolicyConnection, actor: ActorContext, resource_id: str
    ) -> None:
        self._require_transaction(connection)
        self.resource_access.assert_access(connection, actor, resource_id)

    def place_hold(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        resource_id: str,
        reason: SecurityReason,
    ) -> SecurityHold:
        self._require_transaction(connection)
        event_id = self._event_id()
        row = connection.execute(
            "INSERT INTO security_holds "
            "(hold_id,tenant_id,resource_id,reason_code,state,created_by,audit_event_id) "
            "VALUES (%s,%s,%s,%s,'ACTIVE',%s,%s) "
            "ON CONFLICT (tenant_id,resource_id) WHERE state = 'ACTIVE' DO NOTHING "
            "RETURNING *",
            (
                "hold_" + uuid4().hex,
                actor.tenant_id,
                resource_id,
                reason.value,
                actor.actor_id,
                event_id,
            ),
        ).fetchone()
        if row is None:
            row = connection.execute(
                "SELECT * FROM security_holds WHERE tenant_id = %s AND resource_id = %s "
                "AND state = 'ACTIVE' FOR UPDATE",
                (actor.tenant_id, resource_id),
            ).fetchone()
            if row is None:
                raise ServiceUnavailable("Security hold state unavailable")
            return self._hold(row)
        hold = self._hold(row)
        self._append_event(
            connection,
            actor,
            SecurityEventAction.HOLD_PLACED,
            SecurityDecision.PLACE_HOLD,
            resource_id,
            reason,
            hold.state.value,
            event_id,
        )
        return hold

    def clear_hold(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        hold_id: str,
        reason: SecurityReason,
    ) -> SecurityHold | None:
        self._require_transaction(connection)
        if actor.role != Role.DEMO_ADMIN or "security:review" not in actor.scopes:
            raise ScopeDenied("Resource unavailable")
        candidate = connection.execute(
            "SELECT resource_id FROM security_holds WHERE tenant_id = %s AND hold_id = %s",
            (actor.tenant_id, hold_id),
        ).fetchone()
        if candidate is None:
            return None
        resource_id = candidate["resource_id"]
        self.resource_access.assert_access(connection, actor, resource_id)
        event_id = self._event_id()
        row = connection.execute(
            "UPDATE security_holds SET state = 'CLEARED', cleared_by = %s, "
            "cleared_at = clock_timestamp(), audit_event_id = %s "
            "WHERE tenant_id = %s AND hold_id = %s AND resource_id = %s AND state = 'ACTIVE' "
            "RETURNING *",
            (actor.actor_id, event_id, actor.tenant_id, hold_id, resource_id),
        ).fetchone()
        if row is None:
            row = connection.execute(
                "SELECT * FROM security_holds WHERE tenant_id = %s AND hold_id = %s",
                (actor.tenant_id, hold_id),
            ).fetchone()
            return self._hold(row) if row else None
        hold = self._hold(row)
        self._append_event(
            connection,
            actor,
            SecurityEventAction.HOLD_CLEARED,
            SecurityDecision.CLEAR_HOLD,
            hold.resource_id,
            reason,
            hold.state.value,
            event_id,
        )
        return hold

    def create_case(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        resource_id: str,
        reason: SecurityReason,
        evidence_ids: tuple[str, ...],
    ) -> SecurityCase:
        self._require_transaction(connection)
        case_id = "case_" + uuid4().hex
        event_id = self._event_id()
        row = connection.execute(
            "INSERT INTO security_cases "
            "(case_id,tenant_id,resource_id,reason_code,state,evidence_ids,"
            "opened_by,audit_event_id) "
            "VALUES (%s,%s,%s,%s,'OPEN',%s,%s,%s) RETURNING *",
            (
                case_id,
                actor.tenant_id,
                resource_id,
                reason.value,
                list(evidence_ids),
                actor.actor_id,
                event_id,
            ),
        ).fetchone()
        if row is None:
            raise ServiceUnavailable("Security case unavailable")
        case = self._case(row)
        self._append_event(
            connection,
            actor,
            SecurityEventAction.CASE_CREATED,
            SecurityDecision.OPEN_CASE,
            case.resource_id,
            reason,
            case.state.value,
            event_id,
        )
        return case

    def case(
        self, connection: PolicyConnection, actor: ActorContext, case_id: str
    ) -> SecurityCase | None:
        self._require_transaction(connection)
        row = connection.execute(
            "SELECT * FROM security_cases WHERE tenant_id = %s AND case_id = %s",
            (actor.tenant_id, case_id),
        ).fetchone()
        if row is None:
            return None
        if row["opened_by"] != actor.actor_id:
            self.resource_access.assert_access(connection, actor, row["resource_id"])
        return self._case(row)

    def cases(self, connection: PolicyConnection, actor: ActorContext) -> tuple[SecurityCase, ...]:
        self._require_transaction(connection)
        reviewer = actor.role.value == "DEMO_ADMIN" and "security:review" in actor.scopes
        predicate = "" if reviewer else "AND opened_by = %s"
        params: Sequence[str] = (
            (actor.tenant_id,) if reviewer else (actor.tenant_id, actor.actor_id)
        )
        rows = connection.execute(
            "SELECT * FROM security_cases WHERE tenant_id = %s "
            + predicate
            + " ORDER BY updated_at DESC, id DESC LIMIT 100",
            params,
        ).fetchall()
        return tuple(self._case(row) for row in rows)

    def decide_case(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        case_id: str,
        decision: SecurityCaseDecision,
        reason: SecurityReason,
    ) -> SecurityCase | None:
        self._require_transaction(connection)
        if actor.role != Role.DEMO_ADMIN or "security:review" not in actor.scopes:
            raise ScopeDenied("Resource unavailable")
        candidate = connection.execute(
            "SELECT resource_id FROM security_cases WHERE tenant_id = %s AND case_id = %s",
            (actor.tenant_id, case_id),
        ).fetchone()
        if candidate is None:
            return None
        resource_id = candidate["resource_id"]
        self.resource_access.assert_access(connection, actor, resource_id)
        current = connection.execute(
            "SELECT * FROM security_cases WHERE tenant_id = %s AND case_id = %s FOR UPDATE",
            (actor.tenant_id, case_id),
        ).fetchone()
        if current is None:
            return None
        previous_state = SecurityCaseState(current["state"])
        if decision.value == previous_state.value:
            return self._case(current)
        if decision not in _CASE_TRANSITIONS[previous_state]:
            raise SecurityCaseConflict("SECURITY_CASE_TRANSITION_INVALID")
        event_id = self._event_id()
        row = connection.execute(
            "UPDATE security_cases SET state = %s, updated_at = clock_timestamp(), "
            "audit_event_id = %s WHERE tenant_id = %s AND case_id = %s "
            "AND state = %s RETURNING *",
            (
                decision.value,
                event_id,
                actor.tenant_id,
                case_id,
                previous_state.value,
            ),
        ).fetchone()
        if row is None:
            raise SecurityCaseConflict("SECURITY_CASE_CHANGED")
        case = self._case(row)
        security_decision = {
            SecurityCaseDecision.UNDER_REVIEW: SecurityDecision.UNDER_REVIEW,
            SecurityCaseDecision.RESOLVED: SecurityDecision.RESOLVE_CASE,
            SecurityCaseDecision.ESCALATED: SecurityDecision.ESCALATE_CASE,
        }[decision]
        self._append_event(
            connection,
            actor,
            SecurityEventAction.CASE_REVIEWED,
            security_decision,
            case.resource_id,
            reason,
            case.state.value,
            event_id,
        )
        return case

    @staticmethod
    def _hold(row: Record) -> SecurityHold:
        return SecurityHold.model_validate(
            {
                "hold_id": row["hold_id"],
                "resource_id": row["resource_id"],
                "reason": row["reason_code"],
                "state": row["state"],
                "created_by": row["created_by"],
                "created_at": row["created_at"],
                "cleared_by": row["cleared_by"],
                "cleared_at": row["cleared_at"],
                "audit_event_id": row["audit_event_id"],
            }
        )

    @staticmethod
    def _case(row: Record) -> SecurityCase:
        return SecurityCase.model_validate(
            {
                "case_id": row["case_id"],
                "resource_id": row["resource_id"],
                "reason": row["reason_code"],
                "state": row["state"],
                "evidence_ids": row["evidence_ids"],
                "opened_by": row["opened_by"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "audit_event_id": row["audit_event_id"],
            }
        )
