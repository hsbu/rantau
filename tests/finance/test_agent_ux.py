"""UX acceptance at the actual Chat/session/SQL boundary; model transport is isolated."""

from datetime import timedelta

import pytest
from psycopg.types.json import Jsonb

from backend.agent.classifier import IntentClassification
from backend.agent.openrouter_classifier import OpenRouterIntentClassifier
from backend.agent.state import TuitionInput
from backend.contracts.enums import FaultMode, Intent
from backend.finance.provider import set_fault
from tests.finance.conftest import TENANT
from tests.finance.test_agent_approval import confirmed, decide, no_debit
from tests.finance.test_agent_runtime import message, student_client
from tests.finance.test_agent_runtime import runtime as runtime


def test_unrelated_turn_hides_old_cards_retains_draft_and_changes_no_financial_records(
    runtime, monkeypatch
):
    from tests.finance.test_agent_details import domain, read

    services, _, _ = runtime
    client = student_client(services)
    planned = message(client, "Plan tuition from my own account")
    assert read(client, planned.json()["run_id"]).json()["summary"]["quote"] is not None
    before = domain(services.database)
    original_classify = OpenRouterIntentClassifier.classify

    async def unrelated(self, text):
        return IntentClassification(
            intent=None, needs_clarification=True, reply_kind="UNSUPPORTED_ACADEMIC"
        )

    monkeypatch.setattr(OpenRouterIntentClassifier, "classify", unrelated)
    response = message(client, "Write my essay private-marker")
    assert response.status_code == 200
    assert "academic tutoring" in response.json()["message"]
    assert response.json()["requested_action"] is None
    assert response.json()["tool_events"] == []
    assert read(client, response.json()["run_id"]).json()["summary"] is None
    after = domain(services.database)
    for table in before.keys() - {"agent_conversations", "agent_runs"}:
        assert after[table] == before[table], table
    with services.database.connection() as c:
        state = c.execute("SELECT state FROM agent_conversations").fetchone()["state"]
        assert state["tuition"]["source_account_id"] == "acct_idr_stu_01"
        assert "private-marker" not in str(c.execute("SELECT metadata FROM agent_runs").fetchall())
    monkeypatch.setattr(OpenRouterIntentClassifier, "classify", original_classify)
    resumed = message(client, "Review my tuition")
    assert "Selected:" in resumed.json()["message"]
    assert read(client, resumed.json()["run_id"]).json()["summary"]["quote"] is not None
    no_debit(services.database)


def test_ux_04_provider_unavailable_rechecks_the_original_transfer_without_second_debit(runtime):
    services, _, _ = runtime
    client = confirmed(runtime)
    decide("APPROVED")
    with services.database.connection() as c:
        set_fault(c, TENANT, "mock_remit_a", FaultMode.UNAVAILABLE)
    first = message(client, "continue")
    assert first.status_code == 200
    assert "tuition is not confirmed paid" in first.json()["message"]
    with services.database.connection() as c:
        original = c.execute("SELECT alias, provider_reference FROM transfers").fetchone()
        balance = c.execute(
            "SELECT balance_minor FROM funding_accounts WHERE alias='acct_idr_01'"
        ).fetchone()
    for command in ("check", "continue", "continue"):
        response = message(client, command)
        assert response.status_code == 200
        assert "Payment failed" in response.json()["message"]
        assert "current account balance in Payments" in response.json()["message"]
        assert "Verify university posting" not in response.json()["message"]
    with services.database.connection() as c:
        assert c.execute("SELECT alias, provider_reference FROM transfers").fetchall() == [original]
        assert (
            c.execute(
                "SELECT balance_minor FROM funding_accounts WHERE alias='acct_idr_01'"
            ).fetchone()
            == balance
        )
        assert c.execute("SELECT count(*) AS n FROM spend_entries").fetchone()["n"] == 1
        assert c.execute("SELECT count(*) AS n FROM university_postings").fetchone()["n"] == 0


def test_ux_02_amount_revision_cannot_execute_the_previously_approved_draft(runtime, monkeypatch):
    services, _, _ = runtime
    client = confirmed(runtime)
    decide("APPROVED")

    async def changed_amount(self, text):
        return IntentClassification(
            intent=Intent.TUITION,
            needs_clarification=False,
            tuition=TuitionInput(amount_cny="15000"),
        )

    monkeypatch.setattr(OpenRouterIntentClassifier, "classify", changed_amount)
    changed = message(client, "Change the amount to CNY 15000")
    assert changed.status_code == 200
    assert "full outstanding balance" in changed.json()["message"]
    assert "Selected:" not in changed.json()["message"]
    assert not any(
        e["tool"] == "execute_payment" for e in message(client, "continue").json()["tool_events"]
    )
    with services.database.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM payment_intents").fetchone()["n"] == 1
        assert c.execute("SELECT state FROM approvals").fetchone()["state"] == "APPROVED"
        assert (
            c.execute(
                "SELECT count(*) AS n FROM authority_events WHERE action='APPROVAL_CONSUMED'"
            ).fetchone()["n"]
            == 0
        )
    no_debit(services.database)


@pytest.mark.parametrize("change", ["unknown", "expired"])
def test_ux_05_unknown_or_expired_policy_blocks_chat_confirmation_and_debit(runtime, change):
    services, _, _ = runtime
    with services.database.connection() as c:
        policy = c.execute(
            "SELECT policy FROM university_policies WHERE tenant_id=%s", (TENANT,)
        ).fetchone()["policy"]
        if change == "unknown":
            policy["version"] = "unreviewed_version"
        else:
            now = c.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
            policy["effective_to"] = (now - timedelta(seconds=1)).isoformat()
        c.execute(
            "UPDATE university_policies SET policy=%s WHERE tenant_id=%s", (Jsonb(policy), TENANT)
        )
    client = student_client(services)
    result = message(client, "Plan tuition")
    assert result.status_code == 200
    assert "policy is unknown or expired" in result.json()["message"]
    assert not any(
        e["tool"] in {"get_fx_quotes", "build_tuition_preview"}
        for e in result.json()["tool_events"]
    )
    message(client, "confirm tuition")
    message(client, "continue")
    with services.database.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM payment_intents").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM approvals").fetchone()["n"] == 0
    no_debit(services.database)
