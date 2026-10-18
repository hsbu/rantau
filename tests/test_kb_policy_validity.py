from datetime import UTC, datetime, timedelta, timezone

import pytest

from backend.contracts.models import UniversityPolicy
from backend.demo.seed import FIXTURE_VALIDITY_AFTER, FIXTURE_VALIDITY_BEFORE
from backend.kb.catalog import load_bundle
from backend.kb.guidance import explain_policy, known_policy
from tests.fixtures.data import NOW, POLICY

SEED_TIME = datetime(2026, 10, 17, 9, tzinfo=UTC)


def seeded_policy(at=SEED_TIME, *, topup=False):
    return UniversityPolicy.model_validate(
        POLICY.model_dump()
        | {
            "id": "cn_demo_v1_topup" if topup else POLICY.id,
            "version": "cn_demo_v1_topup" if topup else POLICY.version,
            "topup_allowed": topup,
            "verified_at": at,
            "effective_from": at - FIXTURE_VALIDITY_BEFORE,
            "effective_to": at + FIXTURE_VALIDITY_AFTER,
        }
    )


@pytest.mark.parametrize("topup", [False, True])
@pytest.mark.parametrize("at", [SEED_TIME, NOW, datetime(2027, 1, 2, tzinfo=UTC)])
def test_approved_policy_recognized_at_persisted_seed_time(at, topup):
    bundle = load_bundle()
    policy = seeded_policy(at, topup=topup)
    assert known_policy(policy, bundle, at)
    assert bundle.simulation.policy == POLICY


def test_citation_uses_stored_validity_without_rebasing_official_evidence():
    policy = seeded_policy()
    text = explain_policy(policy, load_bundle(), SEED_TIME)
    assert (
        f"Validity: {policy.effective_from.isoformat()} to {policy.effective_to.isoformat()}"
        in text
    )
    assert "48 elapsed hours" in text
    assert "Partial payments: not allowed; top-ups: not allowed" in text
    assert "payment period is 2026-08-10 to 2026-09-10" in text
    assert "current applicability requires rechecking" in text


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "unknown_policy"},
        {"version": "unknown_version"},
        {"university_id": "another_university"},
        {"term_id": "another_term"},
        {"posting_window_hours": 24},
        {"partial_payment_allowed": True},
        {"topup_allowed": True},
        {"required_references": ("different reference",)},
        {"source_url": "https://iczu.zju.edu.cn/"},
        {"certainty": "UNKNOWN"},
        {"verified_at": SEED_TIME + timedelta(seconds=1)},
        {"effective_from": SEED_TIME - FIXTURE_VALIDITY_BEFORE - timedelta(seconds=1)},
        {"effective_to": SEED_TIME + FIXTURE_VALIDITY_AFTER + timedelta(seconds=1)},
    ],
)
def test_rebasing_cannot_disguise_changed_rules_or_independent_date_edits(changes):
    policy = UniversityPolicy.model_validate(seeded_policy().model_dump() | changes)
    assert not known_policy(policy, load_bundle(), SEED_TIME)


def test_stored_policy_expires_and_is_not_renewed_by_the_query_clock():
    policy = seeded_policy()
    assert known_policy(policy, load_bundle(), policy.effective_to - timedelta(microseconds=1))
    assert not known_policy(policy, load_bundle(), policy.effective_to)
    assert not known_policy(policy, load_bundle(), policy.effective_to + timedelta(days=365))
    assert not known_policy(
        policy, load_bundle(), policy.effective_from - timedelta(microseconds=1)
    )


def test_future_seed_cannot_make_a_not_yet_verified_policy_usable():
    policy = seeded_policy(SEED_TIME + timedelta(hours=1))
    assert policy.usable_at(SEED_TIME)  # Its backdated window alone is insufficient.
    assert not known_policy(policy, load_bundle(), SEED_TIME)


def test_timezone_offsets_are_equivalent_and_naive_query_clock_is_rejected():
    local_time = SEED_TIME.astimezone(timezone(timedelta(hours=7)))
    assert known_policy(seeded_policy(local_time), load_bundle(), SEED_TIME)
    assert known_policy(seeded_policy(), load_bundle(), local_time)
    with pytest.raises(ValueError, match="aware clock"):
        known_policy(seeded_policy(), load_bundle(), SEED_TIME.replace(tzinfo=None))


def test_seeded_policy_cannot_replace_a_missing_reviewed_bundle():
    assert not known_policy(seeded_policy(), None, SEED_TIME)


def test_topup_permission_requires_its_exact_reviewed_variant_identity():
    variant = seeded_policy(topup=True)
    assert known_policy(variant, load_bundle(), SEED_TIME)
    for changes in (
        {"id": POLICY.id},
        {"version": POLICY.version},
        {"topup_allowed": False},
        {"partial_payment_allowed": True},
        {"posting_window_hours": 24},
        {"required_references": ("student ID",)},
        {"source_url": "https://iczu.zju.edu.cn/"},
    ):
        changed = UniversityPolicy.model_validate(variant.model_dump() | changes)
        assert not known_policy(changed, load_bundle(), SEED_TIME)
    assert "Partial payments: not allowed; top-ups: allowed" in explain_policy(
        variant, load_bundle(), SEED_TIME
    )
    assert not known_policy(variant, load_bundle(), variant.effective_to)
    assert not known_policy(variant, None, SEED_TIME)
