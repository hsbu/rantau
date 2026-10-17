"""Transaction-bound security holds, cases and redacted audit operations."""

from enum import StrEnum
from typing import Protocol

from pydantic import AwareDatetime, TypeAdapter

from backend.authz.policy_repository import PolicyConnection
from backend.contracts.enums import Role
from backend.contracts.models import ActorContext, Contract, Identifier, ScopeDenied


class SecurityReason(StrEnum):
    UNKNOWN_BENEFICIARY = "UNKNOWN_BENEFICIARY"
    BENEFICIARY_MISMATCH = "BENEFICIARY_MISMATCH"
    BENEFICIARY_CHANGE_REQUESTED = "BENEFICIARY_CHANGE_REQUESTED"
    PROMPT_INJECTION = "PROMPT_INJECTION"
    SCAM_INDICATOR = "SCAM_INDICATOR"
    POLICY_REVIEW = "POLICY_REVIEW"


class SecurityCaseState(StrEnum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class SecurityCaseDecision(StrEnum):
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class SecurityHoldState(StrEnum):
    ACTIVE = "ACTIVE"
    CLEARED = "CLEARED"


class SecurityEventAction(StrEnum):
    HOLD_PLACED = "HOLD_PLACED"
    HOLD_CLEARED = "HOLD_CLEARED"
    CASE_CREATED = "CASE_CREATED"
    CASE_REVIEWED = "CASE_REVIEWED"


class SecurityDecision(StrEnum):
    PLACE_HOLD = "PLACE_HOLD"
    CLEAR_HOLD = "CLEAR_HOLD"
    OPEN_CASE = "OPEN_CASE"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVE_CASE = "RESOLVE_CASE"
    ESCALATE_CASE = "ESCALATE_CASE"


class SecurityEventState(StrEnum):
    ACTIVE = "ACTIVE"
    CLEARED = "CLEARED"
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


_IDENTIFIER_ADAPTER = TypeAdapter(Identifier)


class SecurityHold(Contract):
    hold_id: Identifier
    resource_id: Identifier
    reason: SecurityReason
    state: SecurityHoldState
    created_by: Identifier
    created_at: AwareDatetime
    cleared_by: Identifier | None = None
    cleared_at: AwareDatetime | None = None
    audit_event_id: Identifier


class SecurityCase(Contract):
    case_id: Identifier
    resource_id: Identifier
    reason: SecurityReason
    state: SecurityCaseState
    evidence_ids: tuple[Identifier, ...]
    opened_by: Identifier
    created_at: AwareDatetime
    updated_at: AwareDatetime
    audit_event_id: Identifier


class SecurityEvent(Contract):
    audit_event_id: Identifier
    actor_id: Identifier
    action: SecurityEventAction
    decision: SecurityDecision
    resource_id: Identifier
    reason: SecurityReason
    state: SecurityEventState
    created_at: AwareDatetime


class SecurityResourceAccess(Protocol):
    """Trusted Dev C adapter locks and validates scoped resource access.

    For DEMO_ADMIN review calls, it must verify the current tenant relationship
    and hold the resource lock before B takes a security-row lock.
    """

    def assert_access(
        self, connection: PolicyConnection, actor: ActorContext, resource_id: str
    ) -> None: ...


class SecurityCaseRepository(Protocol):
    """Use the supplied transaction and the policy repository's lock order.

    Implementations must resolve aliases inside the actor's tenant, lock and
    verify the actor's relationship to each resource, write each event in the
    same transaction as its state change, and never persist evidence contents,
    credentials, balances, or raw chat text. Case lists must be relationship-
    scoped and bounded. Hold changes follow C account/resource then B security
    row lock order; execution reads active holds under the same locks.
    """

    def assert_resource_access(
        self, connection: PolicyConnection, actor: ActorContext, resource_id: str
    ) -> None: ...

    def place_hold(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        resource_id: str,
        reason: SecurityReason,
    ) -> SecurityHold: ...

    def clear_hold(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        hold_id: str,
        reason: SecurityReason,
    ) -> SecurityHold | None: ...

    def create_case(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        resource_id: str,
        reason: SecurityReason,
        evidence_ids: tuple[str, ...],
    ) -> SecurityCase: ...

    def case(
        self, connection: PolicyConnection, actor: ActorContext, case_id: str
    ) -> SecurityCase | None: ...

    def cases(
        self, connection: PolicyConnection, actor: ActorContext
    ) -> tuple[SecurityCase, ...]: ...

    def decide_case(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        case_id: str,
        decision: SecurityCaseDecision,
        reason: SecurityReason,
    ) -> SecurityCase | None: ...


class SecurityCaseService:
    """Authorize case operations; repository writes must share caller transaction."""

    def __init__(self, repository: SecurityCaseRepository) -> None:
        self.repository = repository

    @staticmethod
    def _may_place(actor: ActorContext) -> bool:
        return actor.role in {Role.STUDENT, Role.SPONSOR} and (
            "payment:propose" in actor.scopes or "security:hold" in actor.scopes
        )

    @staticmethod
    def _may_read(actor: ActorContext) -> bool:
        return (
            actor.role == Role.STUDENT
            and "student:read" in actor.scopes
            or actor.role == Role.SPONSOR
            and "sponsor:read" in actor.scopes
            or actor.role == Role.DEMO_ADMIN
            and "security:review" in actor.scopes
        )

    @staticmethod
    def _may_review(actor: ActorContext) -> bool:
        return actor.role == Role.DEMO_ADMIN and "security:review" in actor.scopes

    def place_hold(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        resource_id: str,
        reason: SecurityReason,
    ) -> SecurityHold:
        if not self._may_place(actor):
            raise ScopeDenied("Resource unavailable")
        resource_id = _IDENTIFIER_ADAPTER.validate_python(resource_id)
        self.repository.assert_resource_access(connection, actor, resource_id)
        return self.repository.place_hold(connection, actor, resource_id, reason)

    def clear_hold(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        hold_id: str,
        reason: SecurityReason,
    ) -> SecurityHold:
        if not self._may_review(actor):
            raise ScopeDenied("Resource unavailable")
        hold_id = _IDENTIFIER_ADAPTER.validate_python(hold_id)
        hold = self.repository.clear_hold(connection, actor, hold_id, reason)
        if hold is None:
            raise ScopeDenied("Resource unavailable")
        return hold

    def create_case(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        resource_id: str,
        reason: SecurityReason,
        evidence_ids: tuple[str, ...] = (),
    ) -> SecurityCase:
        if not self._may_place(actor):
            raise ScopeDenied("Resource unavailable")
        if len(evidence_ids) > 20:
            raise ValueError("Evidence references are invalid")
        resource_id = _IDENTIFIER_ADAPTER.validate_python(resource_id)
        validated_evidence = tuple(
            _IDENTIFIER_ADAPTER.validate_python(item) for item in evidence_ids
        )
        if len(set(validated_evidence)) != len(validated_evidence):
            raise ValueError("Evidence references are invalid")
        self.repository.assert_resource_access(connection, actor, resource_id)
        return self.repository.create_case(
            connection, actor, resource_id, reason, validated_evidence
        )

    def get_case(
        self, connection: PolicyConnection, actor: ActorContext, case_id: str
    ) -> SecurityCase:
        if not self._may_read(actor):
            raise ScopeDenied("Resource unavailable")
        case_id = _IDENTIFIER_ADAPTER.validate_python(case_id)
        case = self.repository.case(connection, actor, case_id)
        if case is None:
            raise ScopeDenied("Resource unavailable")
        return case

    def list_cases(
        self, connection: PolicyConnection, actor: ActorContext
    ) -> tuple[SecurityCase, ...]:
        if not self._may_read(actor):
            raise ScopeDenied("Resource unavailable")
        return self.repository.cases(connection, actor)

    def decide_case(
        self,
        connection: PolicyConnection,
        actor: ActorContext,
        case_id: str,
        decision: SecurityCaseDecision,
        reason: SecurityReason,
    ) -> SecurityCase:
        if not self._may_review(actor):
            raise ScopeDenied("Resource unavailable")
        case_id = _IDENTIFIER_ADAPTER.validate_python(case_id)
        case = self.repository.decide_case(connection, actor, case_id, decision, reason)
        if case is None:
            raise ScopeDenied("Resource unavailable")
        return case
