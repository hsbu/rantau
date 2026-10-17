"""Reusable scoped read guards; consent never confers financial authority."""

from backend.authz.service import AuthService
from backend.contracts.auth import SHARED_FIELDS, SharedField
from backend.contracts.enums import Role
from backend.contracts.models import ActorContext, ScopeDenied


class AccessPolicy:
    def __init__(self, service: AuthService) -> None:
        self.service = service

    def require_owner(self, actor: ActorContext, tenant_id: str, owner_id: str) -> None:
        with self.service.database.connection() as connection:
            self.service.current_actor(connection, actor)
            if actor.tenant_id != tenant_id or actor.actor_id != owner_id:
                raise ScopeDenied("Resource unavailable")

    def require_sponsor(self, actor: ActorContext, tenant_id: str, owner_id: str) -> None:
        self.require_owner(actor, tenant_id, owner_id)
        if actor.role != Role.SPONSOR or "sponsor:approve" not in actor.scopes:
            raise ScopeDenied("Resource unavailable")

    def require_student_fields(
        self, actor: ActorContext, tenant_id: str, student_id: str, fields: frozenset[SharedField]
    ) -> None:
        with self.service.database.connection() as connection:
            self.service.current_actor(connection, actor)
            if actor.tenant_id != tenant_id or not fields or not fields <= SHARED_FIELDS:
                raise ScopeDenied("Resource unavailable")
            if actor.role == Role.STUDENT and actor.actor_id == student_id:
                if "student:read" not in actor.scopes:
                    raise ScopeDenied("Resource unavailable")
                return
            if actor.role != Role.SPONSOR or "sponsor:read" not in actor.scopes:
                raise ScopeDenied("Resource unavailable")
            grant = connection.execute(
                """SELECT 1 FROM student_sponsor_consents g
                JOIN actors a ON a.tenant_id = g.tenant_id AND a.actor_id = g.student_id
                WHERE g.tenant_id = %s AND g.student_id = %s AND g.sponsor_id = %s
                  AND a.active AND a.role = 'STUDENT' AND g.revoked_at IS NULL
                  AND g.expires_at > now() AND g.allowed_shared_fields @> %s::text[]""",
                (tenant_id, student_id, actor.actor_id, sorted(fields)),
            ).fetchone()
            if grant is None:
                raise ScopeDenied("Resource unavailable")
