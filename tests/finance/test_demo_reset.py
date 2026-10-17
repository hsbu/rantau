from datetime import UTC, datetime

import pytest

from backend.contracts.models import UniversityPolicy
from backend.demo.reset import reset_demo_fixture
from tests.finance.conftest import TENANT


def rows(database, sql, params=()):
    with database.connection() as connection:
        return connection.execute(sql, params).fetchall()


def test_seed_provides_the_spec_fixture(seeded):
    obligation = rows(seeded, "SELECT * FROM tuition_obligations")[0]
    assert obligation["alias"] == "obl_2026_demo_01"
    assert obligation["amount_due_minor"] == 2_000_000 and obligation["currency"] == "CNY"
    assert obligation["due_at"] == datetime(2026, 11, 21, 9, tzinfo=UTC)
    assert {r["alias"] for r in rows(seeded, "SELECT alias FROM fx_quotes")} == {
        "quote_001",
        "quote_002",
    }
    assert {r["alias"] for r in rows(seeded, "SELECT alias FROM funding_accounts")} == {
        "acct_idr_01",
        "acct_idr_stu_01",
    }


def test_seeded_policy_is_synthetic_current_and_keeps_the_agreed_rules(seeded):
    stored = rows(seeded, "SELECT policy, synthetic FROM university_policies")[0]
    policy = UniversityPolicy.model_validate(stored["policy"])
    now = rows(seeded, "SELECT clock_timestamp() AS now")[0]["now"]
    assert stored["synthetic"] and policy.usable_at(now)
    assert (policy.posting_window_hours, policy.partial_payment_allowed, policy.topup_allowed) == (
        48,
        False,
        False,
    )


def test_each_reset_starts_a_new_run_and_leaves_identities_alone(seeded):
    actors_before = rows(seeded, "SELECT actor_id FROM actors ORDER BY actor_id")
    first = rows(seeded, "SELECT run_no FROM demo_state")[0]["run_no"]
    second = reset_demo_fixture(seeded, TENANT, "tuition_happy_path")
    assert second == first + 1
    assert rows(seeded, "SELECT actor_id FROM actors ORDER BY actor_id") == actors_before
    assert len(rows(seeded, "SELECT 1 FROM funding_accounts")) == 2


def test_the_forged_beneficiary_scenario_adds_only_an_unverified_payee(seeded):
    reset_demo_fixture(seeded, TENANT, "forged_beneficiary")
    verified = {
        row["alias"]: row["verified"]
        for row in rows(seeded, "SELECT alias, verified FROM beneficiaries")
    }
    assert verified == {"benef_uni_cn_01": True, "benef_unverified_01": False}


def test_an_unknown_scenario_changes_nothing(seeded):
    with pytest.raises(ValueError):
        reset_demo_fixture(seeded, TENANT, "no_such_scenario")
    assert rows(seeded, "SELECT run_no FROM demo_state")[0]["run_no"] == 1
