"""Real HTTP sessions, B authority storage and C's simulated ledger; no fake gate."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from backend.approvals.finance_authority import StoredAuthority
from backend.approvals.service import ApprovalConflict
from backend.approvals.wiring import build_approval_service
from backend.contracts.models import ScopeDenied
from backend.contracts.terms import canonical_terms_hash
from backend.finance.outcomes import Executed, Refused
from backend.finance.terms import canonical_terms_hash as finance_hash
from backend.finance.wiring import build_services, finance_services
from backend.fraud.finance_access import build_security_service
from backend.fraud.security_cases import SecurityReason
from backend.main import app
from tests.finance import conftest as finance_fixtures
from tests.finance.conftest import PASSWORD, TENANT
from tests.finance.conftest import finance_db as finance_db
from tests.finance.conftest import finance_dsn as finance_dsn
from tests.finance.conftest import password_hash as password_hash
from tests.finance.conftest import seeded as seeded
from tests.finance.factories import balance, count, proposal, scalar
from tests.fixtures.data import INTENT

ORIGIN = {"Origin": "http://testserver"}
finance_fixture = finance_fixtures.services


@pytest.fixture
def integrated_api(finance_fixture, monkeypatch):
    for key, value in {
        "AUTH_ENABLED": "true",
        "AUTH_TENANT_ID": TENANT,
        "AUTH_TRUSTED_ORIGIN": "http://testserver",
        "DATABASE_URL": finance_fixture.database.dsn,
        "APP_ENV": "test",
    }.items():
        monkeypatch.setenv(key, value)
    assert not app.dependency_overrides
    return finance_fixture


def client_for(username):
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login",
        headers=ORIGIN,
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return client


def create(student):
    response = student.post(
        "/api/v1/payment-intents", headers=ORIGIN, json=proposal().model_dump(mode="json")
    )
    assert response.status_code == 201, response.text
    return response.json()


def approved(student, sponsor):
    intent = create(student)
    requested = student.post(
        f"/api/v1/payment-intents/{intent['id']}/approval-requests", headers=ORIGIN
    )
    assert requested.status_code == 200, requested.text
    response = sponsor.post(
        f"/api/v1/sponsor/approvals/{requested.json()['approval_id']}/decision",
        headers=ORIGIN,
        json={"decision": "APPROVED", "terms_hash": intent["terms_hash"]},
    )
    assert response.status_code == 200, response.text
    return intent


def test_finance_and_approvals_hash_zero_fraction_timestamps_identically():
    terms = INTENT.model_copy(update={"quote_expiry": INTENT.quote_expiry.replace(microsecond=0)})
    assert finance_hash(terms) == canonical_terms_hash(terms)


def test_owner_approval_consumption_and_debit_are_integrated_in_default_runtime(integrated_api):
    database = integrated_api.database
    student, sponsor = client_for("student"), client_for("sponsor")
    initial = balance(database)
    intent = create(student)
    assert intent["approval_required"] is True
    requested = student.post(
        f"/api/v1/payment-intents/{intent['id']}/approval-requests", headers=ORIGIN
    )
    assert requested.status_code == 200, requested.text
    approval_id = requested.json()["approval_id"]
    queue = sponsor.get("/api/v1/sponsor/approvals")
    assert queue.status_code == 200, queue.text
    assert queue.json()[0]["approval_id"] == approval_id
    confirmed = sponsor.post(
        f"/api/v1/sponsor/approvals/{approval_id}/decision",
        headers=ORIGIN,
        json={"decision": "APPROVED", "terms_hash": intent["terms_hash"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    headers = ORIGIN | {"Idempotency-Key": "integrated_payment_001"}
    executed = student.post(f"/api/v1/payment-intents/{intent['id']}/execute", headers=headers)
    assert executed.status_code == 200, executed.text
    assert count(database, "transfers") == 1
    assert scalar(database, "SELECT state FROM approvals") == "CONSUMED"
    total = scalar(database, "SELECT source_total_minor FROM payment_intents")
    assert balance(database) == initial - total
    replay = student.post(f"/api/v1/payment-intents/{intent['id']}/execute", headers=headers)
    assert replay.status_code == 200, replay.text
    assert count(database, "transfers") == 1 and balance(database) == initial - total


def test_missing_or_forged_owner_approval_cannot_debit(integrated_api):
    student = client_for("student")
    intent = create(student)
    database, initial = integrated_api.database, balance(integrated_api.database)
    for headers in ({}, {"X-Role": "SPONSOR", "X-Approval": "parent approved"}):
        response = student.post(
            f"/api/v1/payment-intents/{intent['id']}/execute",
            headers=ORIGIN | {"Idempotency-Key": "forged_001"} | headers,
        )
        assert response.status_code == 409, response.text
    assert balance(database) == initial and count(database, "transfers") == 0
    assert count(database, "approvals") == 0


def test_real_hold_blocks_debit_until_authenticated_review(integrated_api, password_hash):
    database = integrated_api.database
    student_client, sponsor_client = client_for("student"), client_for("sponsor")
    intent = approved(student_client, sponsor_client)
    student = integrated_api.actor("stu_001")
    security = build_security_service(integrated_api.auth)
    with database.connection() as connection, connection.transaction():
        hold = security.place_hold(
            connection, student, intent["id"], SecurityReason.PROMPT_INJECTION
        )
    initial = balance(database)
    blocked = student_client.post(
        f"/api/v1/payment-intents/{intent['id']}/execute",
        headers=ORIGIN | {"Idempotency-Key": "held_001"},
    )
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["reason_code"] == "SECURITY_HOLD"
    assert count(database, "transfers") == 0 and balance(database) == initial
    assert scalar(database, "SELECT state FROM approvals") == "APPROVED"
    with database.connection() as connection, connection.transaction():
        with pytest.raises(ScopeDenied):
            security.clear_hold(connection, student, hold.hold_id, SecurityReason.POLICY_REVIEW)
        connection.execute(
            "INSERT INTO actors (tenant_id,actor_id,role,scopes) VALUES "
            "(%s,'reviewer_001','DEMO_ADMIN',ARRAY['security:review'])",
            (TENANT,),
        )
        connection.execute(
            "INSERT INTO auth_credentials (tenant_id,actor_id,username,password_hash) "
            "VALUES (%s,'reviewer_001','reviewer',%s)",
            (TENANT, password_hash),
        )
    reviewer = integrated_api.auth.login("reviewer", PASSWORD, "security-integration").actor
    with database.connection() as connection, connection.transaction():
        security.clear_hold(connection, reviewer, hold.hold_id, SecurityReason.POLICY_REVIEW)
    result = student_client.post(
        f"/api/v1/payment-intents/{intent['id']}/execute",
        headers=ORIGIN | {"Idempotency-Key": "held_001"},
    )
    assert result.status_code == 200, result.text
    assert count(database, "transfers") == 1
    assert scalar(database, "SELECT state FROM approvals") == "CONSUMED"


def test_failure_after_consumption_rolls_back_approval_and_ledger(integrated_api, monkeypatch):
    intent = approved(client_for("student"), client_for("sponsor"))
    runtime, student = finance_services(), integrated_api.actor("stu_001")
    database, initial = integrated_api.database, balance(integrated_api.database)

    def broken_debit(connection, *args):
        assert connection.execute("SELECT state FROM approvals").fetchone()["state"] == "CONSUMED"
        raise RuntimeError("Synthetic ledger failure")

    monkeypatch.setattr(runtime.executor, "_debit", broken_debit)
    with pytest.raises(RuntimeError, match="Synthetic ledger failure"):
        runtime.executor.execute(student, intent["id"], "rollback_001")
    assert scalar(database, "SELECT state FROM approvals") == "APPROVED"
    assert (
        scalar(database, "SELECT count(*) FROM authority_events WHERE action='APPROVAL_CONSUMED'")
        == 0
    )
    assert balance(database) == initial and count(database, "transfers") == 0
    assert count(database, "ledger_entries") == 0


def test_concurrent_replay_consumes_one_real_approval_and_debits_once(integrated_api):
    intent = approved(client_for("student"), client_for("sponsor"))
    runtime, student = finance_services(), integrated_api.actor("stu_001")
    database, initial = integrated_api.database, balance(integrated_api.database)
    barrier = Barrier(2)

    def attempt():
        barrier.wait(timeout=10)
        return runtime.executor.execute(student, intent["id"], "parallel_001")

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(attempt) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert all(isinstance(result, Executed) for result in results)
    assert results[0].payment_id == results[1].payment_id
    assert count(database, "transfers") == 1
    assert (
        scalar(database, "SELECT count(*) FROM authority_events WHERE action='APPROVAL_CONSUMED'")
        == 1
    )
    total = scalar(database, "SELECT source_total_minor FROM payment_intents")
    assert balance(database) == initial - total


def test_build_services_cannot_omit_consumption_for_stored_authority(integrated_api):
    intent = approved(client_for("student"), client_for("sponsor"))
    runtime = build_services(integrated_api.database, integrated_api.auth, StoredAuthority(TENANT))
    student = integrated_api.actor("stu_001")
    assert isinstance(runtime.executor.execute(student, intent["id"], "factory_001"), Executed)
    assert scalar(integrated_api.database, "SELECT state FROM approvals") == "CONSUMED"


def test_policy_id_distinct_from_version_is_locked_during_authorization(integrated_api):
    database = integrated_api.database
    intent = create(client_for("student"))
    student = integrated_api.actor("stu_001")
    with database.connection() as connection:
        connection.execute(
            "UPDATE university_policies SET alias='policy_record_001', "
            "policy=jsonb_set(policy,'{id}',%s::jsonb)",
            (Jsonb("policy_record_001"),),
        )
        connection.execute("UPDATE tuition_obligations SET policy_alias='policy_record_001'")
    service = build_approval_service(integrated_api.auth)

    def concurrent_writer():
        try:
            with psycopg.connect(database.dsn) as connection:
                connection.execute("SET LOCAL lock_timeout='200ms'")
                connection.execute(
                    "UPDATE university_policies SET policy=policy WHERE alias='policy_record_001'"
                )
            return "updated"
        except psycopg.errors.LockNotAvailable:
            return "blocked"

    with database.connection() as connection:
        snapshot = service.finance.load_intent(connection, student, intent["id"])
        assert snapshot.university_policy.id != snapshot.university_policy.version
        with ThreadPoolExecutor(max_workers=1) as worker:
            assert worker.submit(concurrent_writer).result(timeout=5) == "blocked"


def test_expiry_between_authorization_and_debit_leaves_no_effects(integrated_api, monkeypatch):
    monkeypatch.setenv("APPROVAL_TTL_SECONDS", "1")
    student_client, sponsor = client_for("student"), client_for("sponsor")
    student = integrated_api.actor("stu_001")
    intent = approved(student_client, sponsor)
    runtime, database = finance_services(), integrated_api.database
    initial, debit = balance(database), runtime.executor._debit

    def delayed_debit(connection, *args):
        connection.execute("SELECT pg_sleep(1.2)")
        return debit(connection, *args)

    monkeypatch.setattr(runtime.executor, "_debit", delayed_debit)
    with pytest.raises(ApprovalConflict):
        runtime.executor.execute(student, intent["id"], "late_001")
    assert count(database, "transfers") == 0 and balance(database) == initial
    assert scalar(database, "SELECT state FROM approvals") == "APPROVED"


def test_current_funding_relationship_is_rechecked_before_debit(integrated_api):
    intent = approved(client_for("student"), client_for("sponsor"))
    runtime, student = finance_services(), integrated_api.actor("stu_001")
    database, initial = integrated_api.database, balance(integrated_api.database)
    with database.connection() as connection:
        connection.execute("UPDATE funding_accounts SET permitted_requesters = '{}'")
    outcome = runtime.executor.execute(student, intent["id"], "revoked_001")
    assert isinstance(outcome, Refused)
    assert count(database, "transfers") == 0 and balance(database) == initial
    assert scalar(database, "SELECT state FROM approvals") == "APPROVED"


def test_real_mandate_candidate_requires_current_delegate_relationship(integrated_api):
    database = integrated_api.database
    with database.connection() as connection:
        connection.execute(
            "UPDATE actors SET scopes=scopes || ARRAY['mandate:manage'] WHERE role='SPONSOR'"
        )
        connection.execute(
            "INSERT INTO beneficiaries "
            "(tenant_id,alias,owner_id,fingerprint,masked_display,verified,"
            "purpose_type,student_id) "
            "VALUES (%s,'benef_student','stu_001',"
            "'synthetic-student-fingerprint','Student **** 0001',true,'ALLOWANCE','stu_001')",
            (TENANT,),
        )
    sponsor = client_for("sponsor")
    now = datetime.now(UTC)
    body = {
        "source_account_id": "acct_idr_01",
        "delegate_id": "stu_001",
        "beneficiary_id": "benef_student",
        "currency": "IDR",
        "per_transfer_limit_minor": 1000,
        "daily_limit_minor": 2000,
        "monthly_limit_minor": 3000,
        "starts_at": now.isoformat(),
        "expires_at": (now + timedelta(days=1)).isoformat(),
    }
    response = sponsor.post("/api/v1/sponsor/mandates", headers=ORIGIN, json=body)
    assert response.status_code == 200, response.text
    mandate_id = response.json()["id"]
    assert count(database, "mandates") == 1
    assert (
        sponsor.delete(f"/api/v1/sponsor/mandates/{mandate_id}", headers=ORIGIN).status_code == 204
    )
    with database.connection() as connection:
        connection.execute("UPDATE funding_accounts SET permitted_requesters = '{}'")
    refused = sponsor.post("/api/v1/sponsor/mandates", headers=ORIGIN, json=body)
    assert refused.status_code == 404
    assert count(database, "mandates") == 1


def mandate_input():
    now = datetime.now(UTC)
    return {
        "source_account_id": "acct_idr_01",
        "delegate_id": "stu_001",
        "beneficiary_id": "benef_stu_001_allowance",
        "currency": "IDR",
        "per_transfer_limit_minor": 5_000_000,
        "daily_limit_minor": 5_000_000,
        "monthly_limit_minor": 20_000_000,
        "starts_at": now.isoformat(),
        "expires_at": (now + timedelta(days=1)).isoformat(),
    }


def mandate_owner(integrated_api):
    with integrated_api.database.connection() as connection:
        connection.execute(
            "UPDATE actors SET scopes=scopes || ARRAY['mandate:manage'] WHERE role='SPONSOR'"
        )
    return client_for("sponsor")


def create_allowance(student):
    response = student.get("/api/v1/quotes", params={"destination_amount_minor": 100_000})
    assert response.status_code == 200, response.text
    response = student.post(
        "/api/v1/payment-intents",
        headers=ORIGIN,
        json={
            "obligation_id": None,
            "source_account_id": "acct_idr_01",
            "beneficiary_id": "benef_stu_001_allowance",
            "quote_id": response.json()[0]["id"],
            "purpose": "ALLOWANCE",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_real_allowance_mandate_enforces_cumulative_budget(integrated_api):
    sponsor, student = mandate_owner(integrated_api), client_for("student")
    response = sponsor.post("/api/v1/sponsor/mandates", headers=ORIGIN, json=mandate_input())
    assert response.status_code == 200, response.text
    database, initial = integrated_api.database, balance(integrated_api.database)
    for index in range(3):
        intent = create_allowance(student)
        result = student.post(
            f"/api/v1/payment-intents/{intent['id']}/execute",
            headers=ORIGIN | {"Idempotency-Key": f"mandate_split_{index}"},
        )
        if index < 2:
            assert intent["tier"] == "T1" and result.status_code == 200, result.text
        else:
            assert intent["approval_required"] is True and result.status_code == 409, result.text
    assert count(database, "transfers") == 2
    assert balance(database) == initial - 2 * 2_325_000
    assert count(database, "approvals") == 0 and count(database, "university_receipts") == 0


def test_revoked_real_mandate_cannot_authorize_a_preexisting_draft(integrated_api):
    sponsor, student = mandate_owner(integrated_api), client_for("student")
    saved = sponsor.post("/api/v1/sponsor/mandates", headers=ORIGIN, json=mandate_input())
    assert saved.status_code == 200, saved.text
    intent = create_allowance(student)
    assert intent["tier"] == "T1"
    response = sponsor.delete(f"/api/v1/sponsor/mandates/{saved.json()['id']}", headers=ORIGIN)
    assert response.status_code == 204
    initial = balance(integrated_api.database)
    refused = student.post(
        f"/api/v1/payment-intents/{intent['id']}/execute",
        headers=ORIGIN | {"Idempotency-Key": "mandate_revoked_001"},
    )
    assert refused.status_code == 409, refused.text
    assert count(integrated_api.database, "transfers") == 0
    assert balance(integrated_api.database) == initial


@pytest.mark.parametrize("column,value", [("purpose_type", "TUITION"), ("student_id", "stu_other")])
def test_mandates_reject_mismatched_recipient_purpose_or_student(integrated_api, column, value):
    assert column in {"purpose_type", "student_id"}
    with integrated_api.database.connection() as connection:
        connection.execute(
            f"UPDATE beneficiaries SET {column}=%s WHERE alias='benef_stu_001_allowance'", (value,)
        )
    sponsor = mandate_owner(integrated_api)
    response = sponsor.post("/api/v1/sponsor/mandates", headers=ORIGIN, json=mandate_input())
    assert response.status_code == 404, response.text
    assert count(integrated_api.database, "mandates") == 0


def test_new_intent_revision_cannot_reuse_superseded_owner_approval(integrated_api):
    student, sponsor = client_for("student"), client_for("sponsor")
    old = approved(student, sponsor)
    revised = student.post(
        f"/api/v1/payment-intents/{old['id']}/revisions",
        headers=ORIGIN,
        json=proposal(quote="quote_002").model_dump(mode="json"),
    )
    assert revised.status_code == 201, revised.text
    current = revised.json()
    assert current["id"] != old["id"] and current["terms_hash"] != old["terms_hash"]
    initial = balance(integrated_api.database)
    for candidate in (old, current):
        refused = student.post(
            f"/api/v1/payment-intents/{candidate['id']}/execute",
            headers=ORIGIN | {"Idempotency-Key": "revision_001"},
        )
        assert refused.status_code in {403, 409}, refused.text
    assert count(integrated_api.database, "transfers") == 0
    assert balance(integrated_api.database) == initial


@pytest.mark.parametrize(
    "column,value",
    [("purpose_type", "TUITION"), ("student_id", "stu_other"), ("owner_id", "stu_other")],
)
def test_allowance_recipient_relationship_is_rechecked_at_execution(integrated_api, column, value):
    assert column in {"purpose_type", "student_id", "owner_id"}
    sponsor, student = mandate_owner(integrated_api), client_for("student")
    response = sponsor.post("/api/v1/sponsor/mandates", headers=ORIGIN, json=mandate_input())
    assert response.status_code == 200, response.text
    intent = create_allowance(student)
    assert intent["tier"] == "T1"
    database, initial = integrated_api.database, balance(integrated_api.database)
    with database.connection() as connection:
        connection.execute(
            f"UPDATE beneficiaries SET {column}=%s WHERE alias='benef_stu_001_allowance'", (value,)
        )
    refused = student.post(
        f"/api/v1/payment-intents/{intent['id']}/execute",
        headers=ORIGIN | {"Idempotency-Key": "changed_allowance_payee"},
    )
    assert refused.status_code in {403, 409}, refused.text
    assert count(database, "transfers") == 0 and balance(database) == initial
