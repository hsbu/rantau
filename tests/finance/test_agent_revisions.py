"""Approved constrained UX-02: explicit replacement and cancellation use real authority/SQL."""

import pytest

from backend.agent.classifier import IntentClassification
from backend.agent.openrouter_classifier import OpenRouterIntentClassifier
from backend.agent.state import TuitionInput
from backend.contracts.enums import Intent
from backend.contracts.models import ServiceUnavailable
from backend.finance.intents import IntentService
from tests.finance.test_agent_approval import confirmed, decide, no_debit
from tests.finance.test_agent_runtime import message, student_client
from tests.finance.test_agent_runtime import runtime as runtime


@pytest.fixture
def edits(runtime, monkeypatch):
    original = OpenRouterIntentClassifier.classify

    async def classify(self, text):
        current = text.rsplit("Current untrusted message:\n", 1)[-1].casefold()
        inputs = (
            TuitionInput(route_preference="EARLIEST_DELIVERY")
            if current == "faster route"
            else TuitionInput(amount_cny="15000")
            if current == "change amount"
            else TuitionInput(full_balance=True)
            if current == "full balance"
            else TuitionInput(recipient_choice="DIFFERENT_RECIPIENT")
            if current == "other recipient"
            else TuitionInput(recipient_choice="VERIFIED_UNIVERSITY")
            if current == "verified recipient"
            else None
        )
        if inputs is None:
            return await original(self, text)
        return IntentClassification(
            intent=Intent.TUITION, needs_clarification=False, tuition=inputs
        )

    monkeypatch.setattr(OpenRouterIntentClassifier, "classify", classify)
    return runtime


def test_confirmed_route_revision_invalidates_old_authority_and_executes_once(edits):
    services, _, _ = edits
    client = confirmed(edits)
    decide("APPROVED")
    with services.database.connection() as c:
        old = c.execute("SELECT alias FROM payment_intents").fetchone()["alias"]
    changed = message(client, "faster route")
    assert "confirm revision" in changed.json()["message"]
    assert "confirm revision" in message(client, "continue").json()["message"]
    with services.database.connection() as c:
        assert c.execute("SELECT state FROM approvals").fetchone()["state"] == "APPROVED"
    for _ in range(2):
        response = message(client, "confirm revision")
        assert response.status_code == 200, response.text
        assert "Waiting for funding-owner approval" in response.json()["message"]
    with services.database.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM payment_intents").fetchone()["n"] == 2
        assert (
            c.execute("SELECT state FROM payment_intents WHERE alias=%s", (old,)).fetchone()[
                "state"
            ]
            == "CANCELLED"
        )
        assert (
            c.execute("SELECT state FROM approvals ORDER BY created_at LIMIT 1").fetchone()["state"]
            == "INVALIDATED_BY_CHANGE"
        )
    stale = client.post(
        f"/api/v1/payment-intents/{old}/execute",
        headers={"Origin": "http://testserver", "Idempotency-Key": "old-revision-key"},
    )
    assert stale.status_code == 403
    assert stale.json()["reason_code"] == "INVALID_SCOPE"
    no_debit(services.database)
    decide("APPROVED")
    assert message(client, "continue").status_code == 200
    assert message(client, "continue").status_code == 200
    with services.database.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM transfers").fetchone()["n"] == 1
        assert (
            c.execute("SELECT amount_minor FROM spend_entries").fetchone()["amount_minor"]
            == 46_050_000
        )


def test_blocked_amount_revision_cancels_old_then_can_be_corrected(edits):
    services, _, _ = edits
    client = confirmed(edits)
    decide("APPROVED")
    changed = message(client, "change amount")
    assert "Requested amount: CNY 15,000.00" in changed.json()["message"]
    for _ in range(2):
        assert "not payable" in message(client, "confirm revision").json()["message"]
    with services.database.connection() as c:
        assert c.execute("SELECT state FROM payment_intents").fetchone()["state"] == "CANCELLED"
        assert (
            c.execute("SELECT state FROM approvals").fetchone()["state"] == "INVALIDATED_BY_CHANGE"
        )
    no_debit(services.database)
    assert "Selected:" in message(client, "full balance").json()["message"]
    replacement = message(client, "confirm revision")
    assert replacement.status_code == 200, replacement.text
    assert "Waiting for funding-owner approval" in replacement.json()["message"]
    with services.database.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM payment_intents").fetchone()["n"] == 2
        assert (
            c.execute("SELECT count(*) AS n FROM approvals WHERE state='PENDING'").fetchone()["n"]
            == 1
        )
    no_debit(services.database)


def test_recipient_draft_stores_no_unverified_account_and_can_be_restored(edits):
    services, _, _ = edits
    client = student_client(services)
    assert message(client, "Use my own account").status_code == 200
    blocked = message(client, "other recipient")
    assert "recipient needs verification" in blocked.json()["message"]
    assert "Selected:" not in blocked.json()["message"]
    assert "Selected:" in message(client, "verified recipient").json()["message"]
    with services.database.connection() as c:
        state = c.execute("SELECT state FROM agent_conversations").fetchone()["state"]["tuition"]
        assert not state["recipient_blocked"]
        assert state["beneficiary_id"] == "benef_uni_cn_01"
    no_debit(services.database)


def test_revision_failure_rolls_back_original_cancellation_and_approval(edits, monkeypatch):
    services, _, _ = edits
    client = confirmed(edits)
    decide("APPROVED")
    message(client, "faster route")
    original = IntentService.revise_in_transaction

    def fail(self, *args):
        original(self, *args)
        raise ServiceUnavailable("Synthetic revision response loss before commit")

    monkeypatch.setattr(IntentService, "revise_in_transaction", fail)
    assert "couldn’t confirm" in message(client, "confirm revision").json()["message"]
    with services.database.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM payment_intents").fetchone()["n"] == 1
        assert c.execute("SELECT state FROM payment_intents").fetchone()["state"] == "AUTHORIZED"
        assert c.execute("SELECT state FROM approvals").fetchone()["state"] == "APPROVED"
        assert c.execute("SELECT count(*) AS n FROM agent_actions").fetchone()["n"] == 1
    no_debit(services.database)
