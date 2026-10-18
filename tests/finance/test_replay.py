import pytest

from backend.demo.replay import FLOWS, build_replay
from tests.finance.conftest import PASSWORD
from tests.finance.factories import balance

OPENING = 150_000_000
TOTAL = 46_025_000


@pytest.fixture
def replay(services):
    student = services.auth.login("student", PASSWORD, "replay-tests").actor
    return build_replay(services.database, services.auth, student)


def test_happy_path_ends_paid_only_after_the_university_posts(replay):
    report = replay.run("happy")
    assert (
        report.facts["provider_status"] == "DELIVERED" and report.facts["tuition_state"] == "PAID"
    )
    assert (report.facts["transfers"], report.facts["debit_legs"], report.facts["postings"]) == (
        1,
        1,
        1,
    )
    assert any("AWAITING_POSTING" in step for step in report.steps)
    assert any("ON_HOLD" in step for step in report.steps)


def test_the_hero_recovery_posts_once_without_a_second_debit(replay, services):
    report = replay.run("hero")
    assert report.facts["tuition_state"] == "PAID"
    assert (report.facts["transfers"], report.facts["debit_legs"], report.facts["postings"]) == (
        1,
        1,
        1,
    )
    assert balance(services.database) == OPENING - TOTAL
    assert any("EXCEPTION" in step for step in report.steps)


def test_the_attack_flow_blocks_the_forged_payee_but_keeps_the_real_one_payable(replay):
    report = replay.run("attack")
    assert any("Execution of the forged payee: refused" in step for step in report.steps)
    assert (report.facts["transfers"], report.facts["debit_legs"]) == (1, 1)
    assert report.facts["provider_status"] == "DELIVERED"


def test_replays_are_repeatable_from_a_clean_reset(replay):
    first = {flow: replay.run(flow).facts for flow in FLOWS}
    second = {flow: replay.run(flow).facts for flow in FLOWS}
    for flow in FLOWS:
        assert first[flow]["tuition_state"] == second[flow]["tuition_state"]
        assert first[flow]["transfers"] == second[flow]["transfers"]
