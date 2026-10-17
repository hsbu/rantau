"""Authenticated, immutable owner decisions; financial facts come from Dev C."""

import hmac
from collections.abc import Callable
from datetime import timedelta
from typing import Literal, TypeVar

import psycopg

from backend.approvals.repository import ApprovalFinanceRepository
from backend.approvals.store import AuthorityStore, Record, database_time, terms_of
from backend.authz.policy_models import PaymentSnapshot
from backend.authz.policy_repository import PolicyConnection
from backend.authz.service import AuthService
from backend.contracts.authority import ApprovalView, MandateRequest, MandateView, ReviewDisplay
from backend.contracts.enums import PaymentState, Role
from backend.contracts.http import SponsorDecisionResult
from backend.contracts.models import (
    ActionIntent,
    ActorContext,
    ApprovalRequest,
    PaymentTerms,
    PolicyDecision,
    ScopeDenied,
    ServiceUnavailable,
)
from backend.contracts.terms import canonical_terms_hash

T = TypeVar("T")


class ApprovalConflict(Exception):
    """Stale, expired, consumed or conflicting authority; safe public code only."""

    def __init__(self, code: str = "AUTHORITY_CONFLICT") -> None:
        safe_codes = {
            "AUTHORITY_CONFLICT",
            "PAYMENT_NOT_REVIEWABLE",
            "AUTHORITY_TERMINAL",
            "AUTHORITY_NOT_CURRENT",
            "APPROVAL_TERMS_MISMATCH",
            "DECISION_ALREADY_RECORDED",
            "MANDATE_LIMIT_EXCEEDED",
            "MANDATE_EXPIRED",
            "EXECUTION_ACTION_REQUIRED",
            "MANDATE_ALREADY_EXISTS",
        }
        self.code = code if code in safe_codes else "AUTHORITY_CONFLICT"
        super().__init__(self.code)


class ApprovalService:
    def __init__(
        self, auth: AuthService, finance: ApprovalFinanceRepository | None, ttl_seconds: int = 600
    ) -> None:
        if not 1 <= ttl_seconds <= 3600:
            raise ValueError("Approval TTL must be between 1 and 3600 seconds")
        self.auth, self.finance, self.ttl_seconds = auth, finance, ttl_seconds

    def _run(
        self,
        actor: ActorContext,
        operation: Callable[[PolicyConnection], T],
        *,
        requires_finance: bool = True,
    ) -> T:
        if requires_finance and self.finance is None:
            raise ServiceUnavailable("Approval finance adapter unavailable")
        conflict: ApprovalConflict | None = None
        with self.auth.database.connection() as connection:
            self.auth.current_actor(connection, actor)
            try:
                result = operation(connection)
            except ApprovalConflict as error:
                # Commit only explicit invalidation/expiry maintenance. Decision,
                # request and C state mutations have their own atomic savepoint.
                conflict = error
            except ScopeDenied:
                raise
            except Exception:
                raise ServiceUnavailable("Authority data unavailable") from None
            self.auth.current_actor(connection, actor)
        if conflict:
            raise conflict
        return result

    def _load(
        self, connection: PolicyConnection, actor: ActorContext, intent_id: str
    ) -> PaymentSnapshot:
        assert self.finance is not None
        try:
            snapshot = self.finance.load_intent(connection, actor, intent_id)
            if (
                snapshot.tenant_id != actor.tenant_id
                or snapshot.account.tenant_id != actor.tenant_id
                or snapshot.intent.id != intent_id
                or actor.actor_id
                not in {
                    snapshot.intent.requested_by,
                    snapshot.account.owner_id,
                }
                or actor.actor_id not in snapshot.authorized_requesters
            ):
                raise ScopeDenied()
            terms = terms_of(snapshot.intent)
            if (
                snapshot.account.owner_id != terms.funding_owner_id
                or snapshot.account.id != terms.source_account_id
                or not hmac.compare_digest(canonical_terms_hash(terms), terms.terms_hash)
            ):
                raise ServiceUnavailable("Trusted current terms unavailable")
            return snapshot
        except (ScopeDenied, ApprovalConflict):
            raise
        except Exception:
            raise ServiceUnavailable("Trusted approval data unavailable") from None

    @staticmethod
    def _owner(actor: ActorContext, owner_id: str) -> None:
        scope = "sponsor:approve" if actor.role == Role.SPONSOR else "payment:execute"
        if (
            actor.role not in {Role.STUDENT, Role.SPONSOR}
            or actor.actor_id != owner_id
            or scope not in actor.scopes
            or (actor.role == Role.STUDENT and "student:read" not in actor.scopes)
        ):
            raise ScopeDenied()

    @staticmethod
    def _reviewable(snapshot: PaymentSnapshot, now: object) -> None:
        # The clock type is supplied by database_time; no caller clock is trusted.
        from datetime import datetime

        assert isinstance(now, datetime)
        intent, quote = snapshot.intent, snapshot.quote
        if (
            not snapshot.account.active
            or not snapshot.account.owner_active
            or snapshot.held
            or snapshot.risk_floor == "T3"
            or intent.tier == "T3"
            or intent.state
            not in {PaymentState.DRAFT, PaymentState.AWAITING_APPROVAL, PaymentState.AUTHORIZED}
            or not snapshot.beneficiary.verified
            or snapshot.beneficiary.id != intent.beneficiary_id
            or snapshot.beneficiary.fingerprint != intent.beneficiary_fingerprint
            or snapshot.beneficiary.owner_id != snapshot.recipient_owner_id
            or quote.expires_at <= now
            or intent.quote_expiry <= now
            or quote.id != intent.quote_id
            or quote.expires_at != intent.quote_expiry
            or quote.source_currency != intent.source_currency
            or quote.destination_currency != intent.destination_currency
            or quote.source_total_minor != intent.source_total_minor
            or quote.destination_amount_minor != intent.destination_amount_minor
            or snapshot.rules.version != intent.policy_version
            or not snapshot.rules.effective_from <= now < snapshot.rules.effective_to
        ):
            raise ApprovalConflict("PAYMENT_NOT_REVIEWABLE")
        if intent.purpose == "TUITION":
            policy, obligation = snapshot.university_policy, snapshot.obligation
            if (
                policy is None
                or obligation is None
                or not policy.usable_at(now)
                or policy.version != intent.policy_version
                or policy.id != obligation.policy_id
                or policy.university_id != obligation.university_id
                or intent.obligation_id != obligation.id
            ):
                raise ApprovalConflict("PAYMENT_NOT_REVIEWABLE")

    def request(self, actor: ActorContext, intent_id: str) -> ApprovalRequest:
        def operation(connection: PolicyConnection) -> ApprovalRequest:
            if actor.role != Role.STUDENT or "payment:propose" not in actor.scopes:
                raise ScopeDenied()
            snapshot = self._load(connection, actor, intent_id)
            if snapshot.intent.requested_by != actor.actor_id:
                raise ScopeDenied()
            store, terms = AuthorityStore(connection), terms_of(snapshot.intent)
            records = store.refresh(actor, terms)
            self._reviewable(snapshot, database_time(connection))
            active = next((row for row in records if row["state"] in {"PENDING", "APPROVED"}), None)
            if active:
                if active["state"] == "APPROVED":
                    raise ApprovalConflict("DECISION_ALREADY_RECORDED")
                return ApprovalRequest(approval_id=active["approval_id"], intent_id=intent_id)
            if any(
                row["state"] in {"REJECTED", "CONSUMED"}
                and row["intent_revision"] == terms.intent_revision
                for row in records
            ):
                raise ApprovalConflict("AUTHORITY_TERMINAL")
            assert self.finance is not None
            display = self.finance.review_display(connection, actor, snapshot)
            if display.source_principal_minor + display.fee_minor != terms.source_total_minor:
                raise ServiceUnavailable("Trusted review cost unavailable")
            now = database_time(connection)
            expires_at = min(terms.quote_expiry, now + timedelta(seconds=self.ttl_seconds))
            self.auth.current_actor(connection, actor)
            self._reviewable(snapshot, now)
            with connection.transaction():
                row = store.create(actor, terms, display, expires_at)
                self.finance.set_intent_state(
                    connection, actor, snapshot.intent, PaymentState.AWAITING_APPROVAL
                )
            return ApprovalRequest(approval_id=row["approval_id"], intent_id=intent_id)

        return self._run(actor, operation)

    def decide(
        self,
        actor: ActorContext,
        approval_id: str,
        decision: Literal["APPROVED", "REJECTED"],
        digest: str,
    ) -> SponsorDecisionResult:
        def operation(connection: PolicyConnection) -> SponsorDecisionResult:
            store = AuthorityStore(connection)
            initial = store.lookup(actor.tenant_id, approval_id)
            if initial is None:
                raise ScopeDenied()
            self._owner(actor, initial["owner_id"])
            snapshot = self._load(connection, actor, initial["intent_id"])
            self._owner(actor, snapshot.account.owner_id)
            records = store.refresh(actor, terms_of(snapshot.intent))
            row = next(record for record in records if record["approval_id"] == approval_id)
            self.auth.current_actor(connection, actor)
            now = database_time(connection)
            if row["expires_at"] <= now or row["state"] not in {"PENDING", "APPROVED", "REJECTED"}:
                raise ApprovalConflict("AUTHORITY_NOT_CURRENT")
            if (
                not hmac.compare_digest(
                    digest.encode("utf-8"), snapshot.intent.terms_hash.encode("utf-8")
                )
                or row["terms_hash"] != snapshot.intent.terms_hash
                or PaymentTerms.model_validate(row["terms"]) != terms_of(snapshot.intent)
            ):
                raise ApprovalConflict("APPROVAL_TERMS_MISMATCH")
            if row["state"] in {"APPROVED", "REJECTED"}:
                if row["state"] != decision:
                    raise ApprovalConflict("DECISION_ALREADY_RECORDED")
                return self._decision_result(row)
            self._reviewable(snapshot, now)
            assert self.finance is not None
            with connection.transaction():
                updated = connection.execute(
                    "UPDATE approvals SET state = %s, decision_actor_id = %s, "
                    "recorded_at = clock_timestamp() WHERE id = %s AND state = 'PENDING' "
                    "AND expires_at > clock_timestamp() RETURNING *",
                    (decision, actor.actor_id, row["id"]),
                ).fetchone()
                if updated is None:
                    raise ApprovalConflict("AUTHORITY_NOT_CURRENT")
                row = updated
                self.finance.set_intent_state(
                    connection,
                    actor,
                    snapshot.intent,
                    PaymentState.AUTHORIZED if decision == "APPROVED" else PaymentState.REJECTED,
                )
                if row["expires_at"] <= database_time(connection):
                    raise ApprovalConflict("AUTHORITY_NOT_CURRENT")
                store.event(actor, "APPROVAL_DECIDED", approval_id, decision)
            return self._decision_result(row)

        return self._run(actor, operation)

    @staticmethod
    def _decision_result(row: Record) -> SponsorDecisionResult:
        return SponsorDecisionResult(
            approval_id=row["approval_id"],
            decision=row["state"],
            intent_id=row["intent_id"],
            current_terms_hash=row["terms_hash"],
            recorded_at=row["recorded_at"],
        )

    def list_approvals(self, actor: ActorContext) -> list[ApprovalView]:
        def operation(connection: PolicyConnection) -> list[ApprovalView]:
            self._owner(actor, actor.actor_id)
            if actor.role == Role.STUDENT and "student:read" not in actor.scopes:
                raise ScopeDenied()
            store, views = AuthorityStore(connection), []
            for initial in store.for_owner(actor):
                try:
                    snapshot = self._load(connection, actor, initial["intent_id"])
                except ScopeDenied:
                    # A revised request can use another owner's account. Never
                    # disclose that new resource or break the remaining inbox.
                    continue
                records = store.refresh(actor, terms_of(snapshot.intent))
                row = next(
                    record for record in records if record["approval_id"] == initial["approval_id"]
                )
                terms = store.approval(row)
                display = ReviewDisplay.model_validate(row["review"])
                views.append(
                    ApprovalView(
                        **display.model_dump(),
                        approval_id=terms.id,
                        intent_id=terms.intent_id,
                        intent_revision=terms.intent_revision,
                        terms_hash=terms.terms_hash,
                        state=terms.state,
                        expires_at=terms.expires_at,
                        purpose=terms.purpose,
                        source_currency=terms.source_currency,
                        destination_currency=terms.destination_currency,
                        source_total_minor=terms.source_total_minor,
                        destination_amount_minor=terms.destination_amount_minor,
                    )
                )
            return views

        return self._run(actor, operation)

    def invalidate_for_revision(
        self, connection: PolicyConnection, actor: ActorContext, intent_id: str
    ) -> None:
        """Backend-only C hook after a terms revision, on C's transaction."""
        if connection.autocommit or connection.closed or self.finance is None:
            raise ServiceUnavailable("Protected authority transaction unavailable")
        self.auth.current_actor(connection, actor)
        scope = "payment:propose" if actor.role == Role.STUDENT else "sponsor:approve"
        if actor.role not in {Role.STUDENT, Role.SPONSOR} or scope not in actor.scopes:
            raise ScopeDenied()
        snapshot = self._load(connection, actor, intent_id)
        AuthorityStore(connection).refresh(actor, terms_of(snapshot.intent))
        self.auth.current_actor(connection, actor)

    def save_mandate(
        self, actor: ActorContext, body: MandateRequest, mandate_id: str | None = None
    ) -> MandateView:
        from backend.approvals.mandates import save_mandate

        return self._run(
            actor, lambda connection: save_mandate(self, connection, actor, body, mandate_id)
        )

    def revoke_mandate(self, actor: ActorContext, mandate_id: str) -> None:
        from backend.approvals.mandates import revoke_mandate

        self._run(
            actor,
            lambda connection: revoke_mandate(self, connection, actor, mandate_id),
            requires_finance=False,
        )

    def list_mandates(self, actor: ActorContext) -> list[MandateView]:
        from backend.approvals.mandates import list_mandates

        return self._run(
            actor, lambda connection: list_mandates(connection, actor), requires_finance=False
        )

    async def authorize_execution(
        self, connection: PolicyConnection, actor: ActorContext, action: ActionIntent
    ) -> PolicyDecision:
        from backend.approvals.execution import authorize_execution

        try:
            return await authorize_execution(connection, self, actor, action)
        except psycopg.Error:
            raise ServiceUnavailable("Authority storage unavailable") from None
