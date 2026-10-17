"""Owner-managed allowance mandate revisions; no spending counters are reset here."""

from typing import TYPE_CHECKING
from uuid import uuid4

from psycopg.types.json import Jsonb

from backend.approvals.service import ApprovalConflict
from backend.approvals.store import AuthorityStore, Record, database_time
from backend.authz.policy_models import MandateSnapshot
from backend.authz.policy_repository import PolicyConnection
from backend.contracts.authority import MandateRequest, MandateView
from backend.contracts.enums import Role
from backend.contracts.models import ActorContext, ScopeDenied

if TYPE_CHECKING:
    from backend.approvals.service import ApprovalService


def _manager(actor: ActorContext) -> None:
    if actor.role != Role.SPONSOR or "mandate:manage" not in actor.scopes:
        raise ScopeDenied()


def _view(row: Record) -> MandateView:
    mandate = AuthorityStore.mandate(row)
    return MandateView(
        id=mandate.id,
        revision=row["revision"],
        source_label=row["source_label"],
        beneficiary_label=row["beneficiary_label"],
        currency=mandate.currency,
        per_transfer_limit_minor=mandate.per_transfer_limit_minor,
        daily_limit_minor=mandate.daily_limit_minor,
        monthly_limit_minor=mandate.monthly_limit_minor,
        starts_at=mandate.starts_at,
        expires_at=mandate.expires_at,
        timezone=row["account_timezone"],
        revoked=mandate.revoked,
    )


def save_mandate(
    service: "ApprovalService",
    connection: PolicyConnection,
    actor: ActorContext,
    body: MandateRequest,
    mandate_id: str | None,
) -> MandateView:
    _manager(actor)
    assert service.finance is not None
    candidate = service.finance.load_mandate_candidate(connection, actor, body)
    account, beneficiary = candidate.account, candidate.beneficiary
    if (
        candidate.tenant_id != actor.tenant_id
        or account.tenant_id != actor.tenant_id
        or account.owner_id != actor.actor_id
        or not account.active
        or not account.owner_active
        or account.id != body.source_account_id
        or account.currency != body.currency
        or not candidate.relationship_verified
        or candidate.delegate_id != body.delegate_id
        or beneficiary.id != body.beneficiary_id
        or not beneficiary.verified
        or beneficiary.owner_id != body.delegate_id
    ):
        raise ScopeDenied()
    delegate = connection.execute(
        "SELECT actor_id FROM actors WHERE tenant_id = %s AND actor_id = %s "
        "AND role = 'STUDENT' AND active FOR SHARE",
        (actor.tenant_id, body.delegate_id),
    ).fetchone()
    if delegate is None:
        raise ScopeDenied()
    if (
        body.per_transfer_limit_minor > account.per_transfer_limit_minor
        or body.daily_limit_minor > account.daily_limit_minor
        or body.monthly_limit_minor > account.monthly_limit_minor
    ):
        raise ApprovalConflict("MANDATE_LIMIT_EXCEEDED")
    prior = None
    if mandate_id:
        prior = connection.execute(
            "SELECT * FROM mandates WHERE tenant_id = %s AND mandate_id = %s "
            "AND owner_id = %s AND current FOR UPDATE",
            (actor.tenant_id, mandate_id, actor.actor_id),
        ).fetchone()
        if prior is None:
            raise ScopeDenied()
    service.auth.current_actor(connection, actor)
    now = database_time(connection)
    if body.expires_at <= now:
        raise ApprovalConflict("MANDATE_EXPIRED")
    existing = connection.execute(
        "SELECT * FROM mandates WHERE tenant_id=%s AND account_id=%s AND delegate_id=%s "
        "AND beneficiary_id=%s AND current AND revoked_at IS NULL FOR UPDATE",
        (actor.tenant_id, account.id, body.delegate_id, beneficiary.id),
    ).fetchone()
    if existing and (prior is None or existing["id"] != prior["id"]):
        if existing["owner_id"] != actor.actor_id:
            raise ScopeDenied()
        if AuthorityStore.mandate(existing).expires_at > now:
            raise ApprovalConflict("MANDATE_ALREADY_EXISTS")
        connection.execute(
            "UPDATE mandates SET revoked_at=clock_timestamp() WHERE id=%s", (existing["id"],)
        )
        AuthorityStore(connection).event(
            actor, "MANDATE_EXPIRED", existing["mandate_id"], "EXPIRED"
        )
    mandate_id = mandate_id or "mandate_" + uuid4().hex
    mandate = MandateSnapshot(
        id=mandate_id,
        owner_id=actor.actor_id,
        delegate_id=body.delegate_id,
        account_id=account.id,
        beneficiary_id=beneficiary.id,
        beneficiary_fingerprint=beneficiary.fingerprint,
        currency=body.currency,
        purpose="ALLOWANCE",
        per_transfer_limit_minor=body.per_transfer_limit_minor,
        daily_limit_minor=body.daily_limit_minor,
        monthly_limit_minor=body.monthly_limit_minor,
        starts_at=body.starts_at,
        expires_at=body.expires_at,
        revoked=False,
    )
    with connection.transaction():
        if prior:
            connection.execute(
                "UPDATE mandates SET current = false, "
                "revoked_at = COALESCE(revoked_at,clock_timestamp()) WHERE id = %s",
                (prior["id"],),
            )
        row = connection.execute(
            "INSERT INTO mandates (mandate_id, tenant_id, owner_id, account_id, delegate_id, "
            "beneficiary_id, revision, payload, source_label, beneficiary_label, account_timezone) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (
                mandate_id,
                actor.tenant_id,
                actor.actor_id,
                account.id,
                body.delegate_id,
                beneficiary.id,
                prior["revision"] + 1 if prior else 1,
                Jsonb(mandate.model_dump(mode="json")),
                candidate.source_label,
                beneficiary.masked_display,
                account.timezone,
            ),
        ).fetchone()
        assert row is not None
        AuthorityStore(connection).event(actor, "MANDATE_SAVED", mandate_id, "ACTIVE")
    return _view(row)


def revoke_mandate(
    service: "ApprovalService", connection: PolicyConnection, actor: ActorContext, mandate_id: str
) -> None:
    _manager(actor)
    row = connection.execute(
        "SELECT * FROM mandates WHERE tenant_id = %s AND mandate_id = %s AND owner_id = %s "
        "AND current FOR UPDATE",
        (actor.tenant_id, mandate_id, actor.actor_id),
    ).fetchone()
    if row is None:
        raise ScopeDenied()
    service.auth.current_actor(connection, actor)
    if row["revoked_at"] is None:
        connection.execute(
            "UPDATE mandates SET revoked_at = clock_timestamp() WHERE id = %s", (row["id"],)
        )
        AuthorityStore(connection).event(actor, "MANDATE_REVOKED", mandate_id, "REVOKED")


def list_mandates(connection: PolicyConnection, actor: ActorContext) -> list[MandateView]:
    if actor.role != Role.SPONSOR or "sponsor:read" not in actor.scopes:
        raise ScopeDenied()
    rows = connection.execute(
        "SELECT * FROM mandates WHERE tenant_id = %s AND owner_id = %s AND current "
        "ORDER BY created_at DESC LIMIT 100",
        (actor.tenant_id, actor.actor_id),
    ).fetchall()
    return [_view(row) for row in rows]
