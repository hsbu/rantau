"""Tenant-scoped authority records on the caller's PostgreSQL transaction."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from backend.authz.policy_models import MandateSnapshot
from backend.authz.policy_repository import PolicyConnection
from backend.contracts.authority import ReviewDisplay
from backend.contracts.models import ActorContext, Approval, PaymentTerms

Record = dict[str, Any]


def database_time(connection: PolicyConnection) -> datetime:
    row = connection.execute("SELECT clock_timestamp() AS now").fetchone()
    assert row is not None
    value: datetime = row["now"]
    return value


def terms_of(value: PaymentTerms) -> PaymentTerms:
    values = {name: getattr(value, name) for name in PaymentTerms.model_fields}
    for name, field in values.items():
        if isinstance(field, datetime):
            if field.utcoffset() is None:
                raise ValueError("Terms require aware timestamps")
            values[name] = field.astimezone(UTC)
    return PaymentTerms.model_validate(values)


class AuthorityStore:
    def __init__(self, connection: PolicyConnection) -> None:
        self.connection = connection

    def event(self, actor: ActorContext, action: str, resource_id: str, state: str) -> None:
        self.connection.execute(
            "INSERT INTO authority_events "
            "(audit_event_id,tenant_id,actor_id,action,resource_id,state) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            ("audit_" + uuid4().hex, actor.tenant_id, actor.actor_id, action, resource_id, state),
        )

    def lookup(self, tenant: str, approval_id: str, *, lock: bool = False) -> Record | None:
        return self.connection.execute(
            "SELECT * FROM approvals WHERE tenant_id = %s AND approval_id = %s"
            + (" FOR UPDATE" if lock else ""),
            (tenant, approval_id),
        ).fetchone()

    def for_intent(self, tenant: str, intent_id: str) -> list[Record]:
        return self.connection.execute(
            "SELECT * FROM approvals WHERE tenant_id = %s AND intent_id = %s "
            "ORDER BY created_at DESC, id DESC FOR UPDATE",
            (tenant, intent_id),
        ).fetchall()

    def for_owner(self, actor: ActorContext) -> list[Record]:
        return self.connection.execute(
            "SELECT * FROM approvals WHERE tenant_id = %s AND owner_id = %s "
            "ORDER BY created_at DESC, id DESC LIMIT 100",
            (actor.tenant_id, actor.actor_id),
        ).fetchall()

    def refresh(self, actor: ActorContext, terms: PaymentTerms) -> list[Record]:
        records = self.for_intent(actor.tenant_id, terms.intent_id)
        now = database_time(self.connection)
        for row in records:
            if row["state"] not in {"REQUESTED", "PENDING", "APPROVED"}:
                continue
            state = (
                "INVALIDATED_BY_CHANGE"
                if PaymentTerms.model_validate(row["terms"]) != terms
                else "EXPIRED"
                if row["expires_at"] <= now
                else None
            )
            if state:
                self.connection.execute(
                    "UPDATE approvals SET state = %s WHERE id = %s", (state, row["id"])
                )
                row["state"] = state
                self.event(actor, "APPROVAL_INVALIDATED", row["approval_id"], state)
        return records

    def create(
        self, actor: ActorContext, terms: PaymentTerms, display: ReviewDisplay, expires_at: datetime
    ) -> Record:
        row = self.connection.execute(
            "INSERT INTO approvals (approval_id,tenant_id,owner_id,intent_id,intent_revision,"
            "terms_hash,terms,review,state,expires_at) VALUES "
            "(%s,%s,%s,%s,%s,%s,%s,%s,'PENDING',%s) RETURNING *",
            (
                "approval_" + uuid4().hex,
                actor.tenant_id,
                terms.funding_owner_id,
                terms.intent_id,
                terms.intent_revision,
                terms.terms_hash,
                Jsonb(terms.model_dump(mode="json")),
                Jsonb(display.model_dump(mode="json")),
                expires_at,
            ),
        ).fetchone()
        assert row is not None
        self.event(actor, "APPROVAL_REQUESTED", row["approval_id"], "PENDING")
        return row

    @staticmethod
    def approval(row: Record) -> Approval:
        return Approval.model_validate(
            row["terms"]
            | {
                "id": row["approval_id"],
                "approver_actor_id": row["decision_actor_id"] or row["owner_id"],
                "expires_at": row["expires_at"],
                "state": row["state"],
                "consumed_at": row["consumed_at"],
            }
        )

    @staticmethod
    def mandate(row: Record) -> MandateSnapshot:
        return MandateSnapshot.model_validate(
            row["payload"] | {"revoked": row["revoked_at"] is not None}
        )

    def mandate_for_payment(
        self, actor: ActorContext, account: str, beneficiary: str, timezone: str
    ) -> MandateSnapshot | None:
        row = self.connection.execute(
            "SELECT * FROM mandates WHERE tenant_id = %s AND account_id = %s AND delegate_id = %s "
            "AND beneficiary_id = %s AND account_timezone = %s "
            "AND current AND revoked_at IS NULL FOR UPDATE",
            (actor.tenant_id, account, actor.actor_id, beneficiary, timezone),
        ).fetchone()
        return self.mandate(row) if row else None
