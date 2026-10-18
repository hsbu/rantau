"""A-02 compatibility against real scoped C reads and PostgreSQL, with no execution."""

import pytest
from psycopg.types.json import Jsonb

from backend.agent.classifier import IntentClassification
from backend.agent.graph import AgentGraph
from backend.agent.state import TuitionInput
from backend.agent.tools import AgentTools
from backend.contracts.enums import Intent
from backend.demo.reset import reset_demo_fixture
from backend.demo.scenarios import SCENARIOS
from backend.finance.ports import FinanceAgentReadPort
from backend.finance.reads import FinanceReads
from backend.kb.catalog import load_bundle
from backend.kb.guidance import known_policy
from backend.university.port import ObligationReader
from tests.agent.test_graph import FixedClassifier
from tests.finance.conftest import TENANT
from tests.fixtures.data import POLICY


class SelfFundedTuition:
    async def classify(self, message):
        return IntentClassification(
            intent=Intent.TUITION,
            needs_clarification=False,
            tuition=TuitionInput(funding_owner="SELF"),
        )


def tools_for(services):
    obligations = ObligationReader(services.database, services.auth, services.transfers)
    port = FinanceAgentReadPort(
        FinanceReads(services.database, services.auth, obligations), obligations
    )
    return AgentTools(port, beneficiary_map={"uni_cn_01": "benef_uni_cn_01"}), port


def assert_no_financial_effects(database, balances):
    with database.connection() as connection:
        assert connection.execute(
            "SELECT alias, balance_minor FROM funding_accounts ORDER BY alias"
        ).fetchall() == balances
        for table in (
            "payment_intents", "transfers", "ledger_entries", "university_postings",
            "reconciliation_cases", "approvals",
        ):
            assert connection.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0


@pytest.mark.parametrize("scenario_id", tuple(SCENARIOS))
async def test_all_seeded_scenarios_have_known_policy_and_read_only_quote_previews(
    services, student, scenario_id
):
    reset_demo_fixture(services.database, TENANT, scenario_id)
    tools, port = tools_for(services)
    policy = await port.policy(student)
    with services.database.connection() as connection:
        now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        balances = connection.execute(
            "SELECT alias, balance_minor FROM funding_accounts ORDER BY alias"
        ).fetchall()
    assert known_policy(policy, load_bundle(), now)
    assert not known_policy(policy, load_bundle(), policy.effective_to)
    assert load_bundle().simulation.policy == POLICY
    guidance = await AgentGraph(FixedClassifier(Intent.ASK_POLICY), tools).run("Policy", student)
    assert f"Fictional university policy {policy.version}" in guidance.message
    assert "authored demo rules, not official university terms" in guidance.message
    if policy.topup_allowed:
        assert "Partial payments: not allowed; top-ups: allowed" in guidance.message
    result = await AgentGraph(SelfFundedTuition(), tools).run("Pay tuition", student)
    assert "Draft intent preview" in result.message
    assert "No payment has been requested or executed" in result.message
    assert any(
        event.tool == "get_fx_quotes" and event.status == "OK" for event in result.tool_events
    )
    assert result.tool_events[-1].tool == "build_tuition_preview"
    assert_no_financial_effects(services.database, balances)


@pytest.mark.parametrize("change", ["rule", "expiry", "version"])
async def test_changed_persisted_policy_cannot_enable_a_quote_preview(services, student, change):
    tools, port = tools_for(services)
    policy = await port.policy(student)
    with services.database.connection() as connection:
        now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        balances = connection.execute(
            "SELECT alias, balance_minor FROM funding_accounts ORDER BY alias"
        ).fetchall()
        update = {
            "rule": {"topup_allowed": True},
            "expiry": {"effective_to": now},
            "version": {"version": "unreviewed_version"},
        }[change]
        connection.execute(
            "UPDATE university_policies SET policy = %s WHERE tenant_id = %s",
            (Jsonb(policy.model_copy(update=update).model_dump(mode="json")), TENANT),
        )
    result = await AgentGraph(SelfFundedTuition(), tools).run("Pay tuition", student)
    assert "policy is unknown or expired" in result.message
    assert not any(
        event.tool in {"get_fx_quotes", "build_tuition_preview"} for event in result.tool_events
    )
    assert_no_financial_effects(services.database, balances)
