import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from backend.approvals.service import ApprovalConflict
from backend.approvals.store import AuthorityStore
from backend.authz.policy_transaction import TransactionAuthorization
from backend.contracts.authority import MandateRequest
from backend.contracts.enums import Decision, PaymentState
from backend.contracts.models import ActionIntent, ScopeDenied, ServiceUnavailable
from backend.contracts.terms import canonical_terms_hash
from tests.approvals.finance import snapshot_now


@pytest.mark.parametrize("expired_fact", ["mandate", "quote", "policy"])
def test_late_t1_expiry_rolls_back_allow_audit(
    authority, student, sponsor, monkeypatch, expired_fact
):
    expiry = datetime.now(UTC) + timedelta(seconds=1.5)
    mandate = mandate_input()
    if expired_fact == "mandate":
        mandate = mandate.model_copy(update={"expires_at": expiry})
    authority.save_mandate(sponsor, mandate)
    snapshot = snapshot_now(routine=True)
    if expired_fact == "quote":
        intent = snapshot.intent.model_copy(update={"quote_expiry": expiry})
        intent = intent.model_copy(update={"terms_hash": canonical_terms_hash(intent)})
        snapshot = snapshot.model_copy(
            update={
                "intent": intent,
                "quote": snapshot.quote.model_copy(update={"expires_at": expiry}),
            }
        )
    elif expired_fact == "policy":
        snapshot = snapshot.model_copy(
            update={"rules": snapshot.rules.model_copy(update={"effective_to": expiry})}
        )
    authority.finance.put(snapshot)
    original = TransactionAuthorization.evaluate

    async def delayed_audit(gate, actor, intent):
        result = await original(gate, actor, intent)
        assert result.decision == Decision.ALLOW
        gate.connection.execute("SELECT pg_sleep(1.6)")
        return result

    monkeypatch.setattr(TransactionAuthorization, "evaluate", delayed_audit)
    with authority.auth.database.connection() as connection:
        with pytest.raises(ApprovalConflict):
            asyncio.run(authority.authorize_execution(connection, student, action(snapshot)))
        assert connection.execute("SELECT count(*) AS n FROM policy_decisions").fetchone()["n"] == 0


def test_expiry_after_t2_consumption_rolls_back_authority_and_audit(
    authority, student, sponsor, monkeypatch
):
    authority.ttl_seconds = 1
    approved(authority, student, sponsor)
    original = AuthorityStore.event

    def delayed_event(store, actor, event_action, resource_id, state):
        original(store, actor, event_action, resource_id, state)
        if event_action == "APPROVAL_CONSUMED":
            store.connection.execute("SELECT pg_sleep(1.1)")

    monkeypatch.setattr(AuthorityStore, "event", delayed_event)
    with authority.auth.database.connection() as connection:
        snapshot = authority.finance.load_intent(connection, student, "intent_001")
        with pytest.raises(ApprovalConflict):
            asyncio.run(authority.authorize_execution(connection, student, action(snapshot)))
        assert connection.execute("SELECT count(*) AS n FROM policy_decisions").fetchone()["n"] == 0
    assert records(authority)[0]["state"] == "APPROVED"
    assert all(row["action"] != "APPROVAL_CONSUMED" for row in records(authority, "events"))


def test_rejected_history_cannot_confirm_a_new_revisions_digest(authority, student, sponsor):
    request = authority.request(student, "intent_001")
    old_digest = authority.list_approvals(sponsor)[0].terms_hash
    authority.decide(sponsor, request.approval_id, "REJECTED", old_digest)
    snapshot = snapshot_now()
    intent = snapshot.intent.model_copy(update={"intent_revision": 2})
    intent = intent.model_copy(update={"terms_hash": canonical_terms_hash(intent)})
    authority.finance.put(snapshot.model_copy(update={"intent": intent}))
    current = authority.request(student, intent.id)
    with pytest.raises(ApprovalConflict, match="APPROVAL_TERMS_MISMATCH"):
        authority.decide(sponsor, request.approval_id, "REJECTED", intent.terms_hash)
    states = {row["approval_id"]: row["state"] for row in records(authority)}
    assert states[request.approval_id] == "REJECTED"
    assert states[current.approval_id] == "PENDING"


def test_non_ascii_digest_is_a_typed_conflict(authority, student, sponsor):
    request = authority.request(student, "intent_001")
    with pytest.raises(ApprovalConflict):
        authority.decide(sponsor, request.approval_id, "APPROVED", "伪造批准")


def test_expiry_during_cas_rolls_back_decision_and_intent(authority, student, sponsor):
    authority.ttl_seconds = 1
    request = authority.request(student, "intent_001")
    digest = records(authority)[0]["terms_hash"]
    authority.finance.delay = 0.6
    with pytest.raises(ApprovalConflict):
        authority.decide(sponsor, request.approval_id, "APPROVED", digest)
    assert records(authority)[0]["state"] != "APPROVED"
    authority.finance.delay = 0
    with authority.auth.database.connection() as connection:
        assert (
            authority.finance.load_intent(connection, student, "intent_001").intent.state
            == PaymentState.AWAITING_APPROVAL
        )


def test_repository_error_is_sanitized_and_request_rolls_back(authority, student, monkeypatch):
    def unavailable(*args):
        raise ValueError("private account information")

    monkeypatch.setattr(authority.finance, "review_display", unavailable)
    with pytest.raises(ServiceUnavailable) as caught:
        authority.request(student, "intent_001")
    assert "private" not in str(caught.value) and not records(authority)


def test_cross_tenant_adapter_error_cannot_invalidate_current_tenant_authority(
    authority, student, sponsor, monkeypatch
):
    approved(authority, student, sponsor)
    snapshot = snapshot_now()
    intent = snapshot.intent.model_copy(update={"intent_revision": 2})
    intent = intent.model_copy(update={"terms_hash": canonical_terms_hash(intent)})
    snapshot = snapshot.model_copy(
        update={
            "tenant_id": "other",
            "intent": intent,
            "account": snapshot.account.model_copy(update={"tenant_id": "other"}),
        }
    )
    monkeypatch.setattr(authority.finance, "load_payment", lambda *args: snapshot)
    with authority.auth.database.connection() as connection:
        assert (
            asyncio.run(
                authority.authorize_execution(connection, student, action(snapshot))
            ).decision
            == Decision.DENY
        )
    assert records(authority)[0]["state"] == "APPROVED"


def test_approved_request_cannot_report_awaiting_approval_again(authority, student, sponsor):
    approved(authority, student, sponsor)
    with pytest.raises(ApprovalConflict):
        authority.request(student, "intent_001")


def test_duplicate_active_mandate_is_a_typed_conflict(authority, sponsor):
    authority.save_mandate(sponsor, mandate_input())
    with pytest.raises(ApprovalConflict):
        authority.save_mandate(sponsor, mandate_input())


def test_expired_mandate_does_not_block_fresh_owner_configuration(authority, sponsor):
    body = mandate_input().model_copy(
        update={"expires_at": datetime.now(UTC) + timedelta(seconds=1)}
    )
    old = authority.save_mandate(sponsor, body)
    with authority.auth.database.connection() as connection:
        connection.execute("SELECT pg_sleep(1.1)")
    new = authority.save_mandate(sponsor, mandate_input())
    assert new.id != old.id
    assert len(records(authority, "mandates")) == 2


def test_mandate_can_be_revoked_when_financial_adapter_is_unavailable(authority, sponsor):
    from backend.approvals.service import ApprovalService

    mandate = authority.save_mandate(sponsor, mandate_input())
    offline = ApprovalService(authority.auth, None)
    offline.revoke_mandate(sponsor, mandate.id)
    assert offline.list_mandates(sponsor)[0].revoked


def test_equivalent_quote_timezone_does_not_break_single_consumption(authority, student, sponsor):
    from datetime import timezone

    approved(authority, student, sponsor)
    with authority.auth.database.connection() as connection:
        snapshot = authority.finance.load_intent(connection, student, "intent_001")
    expiry = snapshot.intent.quote_expiry.astimezone(timezone(timedelta(hours=7)))
    snapshot = snapshot.model_copy(
        update={
            "intent": snapshot.intent.model_copy(update={"quote_expiry": expiry}),
            "quote": snapshot.quote.model_copy(update={"expires_at": expiry}),
        }
    )
    authority.finance.put(snapshot)
    with authority.auth.database.connection() as connection:
        assert (
            asyncio.run(
                authority.authorize_execution(connection, student, action(snapshot))
            ).decision
            == Decision.ALLOW
        )


def test_backend_revision_hook_invalidates_old_authority(authority, student, sponsor):
    approved(authority, student, sponsor)
    with authority.auth.database.connection() as connection:
        snapshot = authority.finance.load_intent(connection, student, "intent_001")
    intent = snapshot.intent.model_copy(update={"intent_revision": 2})
    intent = intent.model_copy(update={"terms_hash": canonical_terms_hash(intent)})
    authority.finance.put(snapshot.model_copy(update={"intent": intent}))
    with authority.auth.database.connection() as connection:
        authority.invalidate_for_revision(connection, student, intent.id)
    assert records(authority)[0]["state"] == "INVALIDATED_BY_CHANGE"


def test_owner_inbox_skips_resource_that_now_uses_another_owners_funds(authority, student, sponsor):
    authority.request(student, "intent_001")
    authority.finance.put(snapshot_now(own=True))
    authority.finance.put(snapshot_now(intent_id="still_owned"))
    authority.request(student, "still_owned")
    assert [view.intent_id for view in authority.list_approvals(sponsor)] == ["still_owned"]


def test_concurrent_opposite_decisions_have_one_winner(authority, student, sponsor):
    request = authority.request(student, "intent_001")
    digest = authority.list_approvals(sponsor)[0].terms_hash

    def decide(value):
        try:
            return authority.decide(sponsor, request.approval_id, value, digest).decision
        except ApprovalConflict:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(decide, ["APPROVED", "REJECTED"]))
    assert outcomes.count("CONFLICT") == 1
    assert records(authority)[0]["state"] in outcomes


def test_consumed_authority_cannot_be_reopened_by_accidental_sql_update(
    authority, student, sponsor
):
    approved(authority, student, sponsor)
    with authority.auth.database.connection() as connection:
        snapshot = authority.finance.load_intent(connection, student, "intent_001")
        assert (
            asyncio.run(
                authority.authorize_execution(connection, student, action(snapshot))
            ).decision
            == Decision.ALLOW
        )
    with pytest.raises(psycopg.errors.RaiseException):
        with psycopg.connect(authority.auth.database.dsn) as connection:
            connection.execute("UPDATE approvals SET state='APPROVED', consumed_at=NULL")


def test_changed_account_timezone_requires_new_mandate_or_owner_approval(
    authority, student, sponsor
):
    authority.save_mandate(sponsor, mandate_input())
    snapshot = snapshot_now(routine=True)
    day = datetime.now(UTC).date()
    snapshot = snapshot.model_copy(
        update={
            "account": snapshot.account.model_copy(update={"timezone": "UTC"}),
            "spending_day": day,
            "spending_month": day.replace(day=1),
        }
    )
    authority.finance.put(snapshot)
    with authority.auth.database.connection() as connection:
        assert (
            asyncio.run(
                authority.authorize_execution(connection, student, action(snapshot))
            ).decision
            == Decision.REQUIRE_APPROVAL
        )


def action(snapshot):
    return ActionIntent(
        action="EXECUTE_PAYMENT",
        resource_id=snapshot.intent.id,
        terms_hash=snapshot.intent.terms_hash,
    )


def records(authority, table="approvals"):
    with authority.auth.database.connection() as connection:
        return connection.execute(
            {
                "approvals": "SELECT * FROM approvals",
                "events": "SELECT * FROM authority_events",
                "mandates": "SELECT * FROM mandates ORDER BY revision",
            }[table]
        ).fetchall()


def approved(authority, student, sponsor):
    request = authority.request(student, "intent_001")
    view = authority.list_approvals(sponsor)[0]
    return request, authority.decide(sponsor, request.approval_id, "APPROVED", view.terms_hash)


def test_owner_decision_is_persistent_and_idempotent(authority, student, sponsor):
    request, first = approved(authority, student, sponsor)
    assert first == authority.decide(
        sponsor, request.approval_id, "APPROVED", first.current_terms_hash
    )
    assert records(authority)[0]["decision_actor_id"] == sponsor.actor_id
    with pytest.raises(ApprovalConflict):
        authority.decide(sponsor, request.approval_id, "REJECTED", first.current_terms_hash)
    assert len(records(authority, "events")) == 2
    assert all(
        "acct_idr_01" not in repr(row) and sponsor.session_id not in repr(row)
        for row in records(authority, "events")
    )


def test_request_retries_reuse_pending_authority(authority, student):
    assert authority.request(student, "intent_001") == authority.request(student, "intent_001")
    assert len(records(authority)) == 1


def test_student_and_forged_context_cannot_approve_parent_funds(authority, student, sponsor):
    request = authority.request(student, "intent_001")
    digest = authority.list_approvals(sponsor)[0].terms_hash
    for actor in (
        student,
        student.model_copy(update={"role": "SPONSOR"}),
        sponsor.model_copy(update={"tenant_id": "other"}),
    ):
        with pytest.raises(ScopeDenied):
            authority.decide(actor, request.approval_id, "APPROVED", digest)
    assert records(authority)[0]["state"] == "PENDING"


def test_own_account_student_confirmation_excludes_parent(authority, student, sponsor):
    authority.finance.put(snapshot_now(own=True))
    request = authority.request(student, "intent_001")
    view = authority.list_approvals(student)[0]
    assert authority.list_approvals(sponsor) == []
    with pytest.raises(ScopeDenied):
        authority.decide(sponsor, request.approval_id, "APPROVED", view.terms_hash)
    assert (
        authority.decide(student, request.approval_id, "APPROVED", view.terms_hash).decision
        == "APPROVED"
    )


def test_review_view_has_costs_but_no_private_terms(authority, student, sponsor):
    authority.request(student, "intent_001")
    data = authority.list_approvals(sponsor)[0].model_dump()
    assert {
        "source_total_minor",
        "destination_amount_minor",
        "fee_minor",
        "terms_hash",
    } <= data.keys()
    assert (
        not {
            "source_account_id",
            "beneficiary_id",
            "funding_owner_id",
            "obligation_id",
            "beneficiary_fingerprint",
            "student_id",
            "balance_minor",
            "terms",
        }
        & data.keys()
    )


@pytest.mark.parametrize(
    "change",
    [
        {"intent_revision": 2},
        {"beneficiary_fingerprint": "changed"},
        {"policy_version": "new"},
        {"source_total_minor": 46_025_001},
    ],
)
def test_old_approval_is_invalidated_when_current_terms_change(authority, student, sponsor, change):
    request, decision = approved(authority, student, sponsor)
    with authority.auth.database.connection() as connection:
        snapshot = authority.finance.load_intent(connection, student, "intent_001")
    intent = snapshot.intent.model_copy(update=change)
    intent = intent.model_copy(update={"terms_hash": canonical_terms_hash(intent)})
    snapshot = snapshot.model_copy(update={"intent": intent})
    authority.finance.put(snapshot)
    with pytest.raises(ApprovalConflict):
        authority.decide(sponsor, request.approval_id, "APPROVED", decision.current_terms_hash)
    with authority.auth.database.connection() as connection:
        outcome = asyncio.run(authority.authorize_execution(connection, student, action(snapshot)))
    assert outcome.decision != Decision.ALLOW
    assert records(authority)[0]["state"] == "INVALIDATED_BY_CHANGE"


def test_expiry_after_delayed_load_cannot_be_approved(authority, student, sponsor):
    authority.ttl_seconds = 1
    request = authority.request(student, "intent_001")
    digest = authority.list_approvals(sponsor)[0].terms_hash
    authority.finance.delay = 1.1
    with pytest.raises(ApprovalConflict):
        authority.decide(sponsor, request.approval_id, "APPROVED", digest)
    assert records(authority)[0]["state"] != "APPROVED"


def test_rejected_decision_marks_intent_and_prevents_execution(authority, student, sponsor):
    request = authority.request(student, "intent_001")
    authority.decide(
        sponsor, request.approval_id, "REJECTED", authority.list_approvals(sponsor)[0].terms_hash
    )
    with authority.auth.database.connection() as connection:
        snapshot = authority.finance.load_intent(connection, student, "intent_001")
        assert snapshot.intent.state == PaymentState.REJECTED
        assert (
            asyncio.run(
                authority.authorize_execution(connection, student, action(snapshot))
            ).decision
            == Decision.DENY
        )


def test_consumption_is_single_use_and_rolls_back_with_caller(authority, student, sponsor):
    approved(authority, student, sponsor)
    with pytest.raises(RuntimeError):
        with authority.auth.database.connection() as connection:
            snapshot = authority.finance.load_intent(connection, student, "intent_001")
            assert (
                asyncio.run(
                    authority.authorize_execution(connection, student, action(snapshot))
                ).decision
                == Decision.ALLOW
            )
            raise RuntimeError("rollback test")
    assert records(authority)[0]["state"] == "APPROVED"
    with authority.auth.database.connection() as connection:
        assert (
            asyncio.run(
                authority.authorize_execution(connection, student, action(snapshot))
            ).decision
            == Decision.ALLOW
        )
    assert records(authority)[0]["state"] == "CONSUMED"
    with authority.auth.database.connection() as connection:
        assert (
            asyncio.run(
                authority.authorize_execution(connection, student, action(snapshot))
            ).decision
            != Decision.ALLOW
        )


def test_two_consumers_have_one_winner(authority, student, sponsor):
    approved(authority, student, sponsor)

    def consume(_):
        with authority.auth.database.connection() as connection:
            snapshot = authority.finance.load_intent(connection, student, "intent_001")
            return asyncio.run(
                authority.authorize_execution(connection, student, action(snapshot))
            ).decision

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(consume, range(2)))
    assert outcomes.count(Decision.ALLOW) == 1
    assert records(authority)[0]["consumed_at"] is not None


def test_immutable_authority_and_audit_reject_overwrites(authority, student, sponsor):
    approved(authority, student, sponsor)
    for sql in (
        "UPDATE approvals SET terms='{}'::jsonb",
        "UPDATE authority_events SET action='FORGED'",
        "DELETE FROM authority_events",
    ):
        with pytest.raises(psycopg.errors.RaiseException):
            with psycopg.connect(authority.auth.database.dsn) as connection:
                connection.execute(sql)


def mandate_input():
    snapshot, now = snapshot_now(routine=True), datetime.now(UTC)
    return MandateRequest(
        source_account_id=snapshot.account.id,
        delegate_id="stu_001",
        beneficiary_id=snapshot.beneficiary.id,
        currency="IDR",
        per_transfer_limit_minor=50_000_000,
        daily_limit_minor=100_000_000,
        monthly_limit_minor=150_000_000,
        starts_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(days=30),
    )


def test_mandate_revision_and_revocation_preserve_history(authority, sponsor):
    first = authority.save_mandate(sponsor, mandate_input())
    second = authority.save_mandate(sponsor, mandate_input(), first.id)
    assert second.id == first.id and second.revision == 2
    assert len(records(authority, "mandates")) == 2
    authority.revoke_mandate(sponsor, first.id)
    assert authority.list_mandates(sponsor)[0].revoked
    assert all(row["revoked_at"] is not None for row in records(authority, "mandates"))


def test_student_or_missing_manage_scope_cannot_configure_mandates(authority, student, sponsor):
    for actor in (student, sponsor.model_copy(update={"scopes": frozenset({"sponsor:approve"})})):
        with pytest.raises(ScopeDenied):
            authority.save_mandate(actor, mandate_input())
    assert not records(authority, "mandates")


def test_revocation_invalidates_allowance_authority(authority, student, sponsor):
    authority.finance.put(snapshot_now(routine=True))
    mandate = authority.save_mandate(sponsor, mandate_input())
    with authority.auth.database.connection() as connection:
        snapshot = authority.finance.load_intent(connection, student, "intent_001")
        assert (
            asyncio.run(
                authority.authorize_execution(connection, student, action(snapshot))
            ).decision
            == Decision.ALLOW
        )
    authority.revoke_mandate(sponsor, mandate.id)
    with authority.auth.database.connection() as connection:
        assert (
            asyncio.run(
                authority.authorize_execution(connection, student, action(snapshot))
            ).decision
            == Decision.REQUIRE_APPROVAL
        )


def test_concurrent_reservations_and_mandate_revision_cannot_reset_cumulative_budget(
    authority, student, sponsor
):
    mandate = authority.save_mandate(sponsor, mandate_input())
    for index in range(3):
        authority.finance.put(snapshot_now(routine=True, intent_id=f"allowance_{index}"))

    def attempt(index):
        with authority.auth.database.connection() as connection:
            snapshot = authority.finance.load_intent(connection, student, f"allowance_{index}")
            outcome = asyncio.run(
                authority.authorize_execution(connection, student, action(snapshot))
            )
            if outcome.decision == Decision.ALLOW:
                connection.execute(
                    "INSERT INTO test_finance_spending VALUES (%s,%s,clock_timestamp())",
                    (snapshot.intent.id, snapshot.intent.source_total_minor),
                )
            return outcome.decision

    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = list(pool.map(attempt, range(3)))
    assert outcomes.count(Decision.ALLOW) == 2 and outcomes.count(Decision.REQUIRE_APPROVAL) == 1
    authority.save_mandate(sponsor, mandate_input(), mandate.id)
    authority.finance.put(snapshot_now(routine=True, intent_id="allowance_after"))
    assert attempt("after") == Decision.REQUIRE_APPROVAL
    with authority.auth.database.connection() as connection:
        assert (
            connection.execute("SELECT sum(amount) AS n FROM test_finance_spending").fetchone()["n"]
            == 92_050_000
        )
