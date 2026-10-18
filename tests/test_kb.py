import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.contracts.models import UniversityPolicy
from backend.kb.catalog import load_bundle
from backend.kb.records import Claim, KnowledgeBundle, ReviewedReference
from tests.fixtures.data import NOW, POLICY


def test_simulator_preserves_approved_fixture_and_its_clock():
    bundle = load_bundle()
    assert bundle.simulation.policy == POLICY
    assert bundle.simulation.policy.usable_at(NOW)
    assert not bundle.simulation.policy.usable_at(datetime(2026, 10, 17, tzinfo=UTC))
    assert not bundle.simulation.policy.usable_at(POLICY.effective_to)
    assert bundle.simulation.usage == "ISOLATED_SIMULATION_ONLY"
    assert bundle.simulation.operational_values == "AUTHORED_SIMULATION"


def test_source_scope_and_payment_period_do_not_establish_current_policy():
    reference = load_bundle().reference
    assert reference.scope.university_id == "zju"
    assert reference.scope.academic_year == "2026-2027"
    assert "Current international" in reference.scope.audience
    assert reference.published_on == date(2026, 8, 8)
    assert reference.payment_period.end < reference.reviewed_on
    assert reference.effective_period is None
    assert reference.applicability == "RECHECK_REQUIRED"
    assert reference.usage == "PROCEDURAL_REFERENCE_ONLY"
    assert reference.review_status == "REVIEWED_DRAFT"
    assert reference.reviewed_by == "DEV_A_AGENT"
    # The reference has no executable policy shape or validity defaults.
    with pytest.raises(ValidationError):
        UniversityPolicy.model_validate(reference.model_dump())


def test_unstated_financial_rules_stay_unknown_despite_simulator_defaults():
    bundle = load_bundle()
    claims = {claim.key: claim for claim in bundle.reference.claims}
    for key in (
        "posting_window_hours",
        "partial_payment_allowed",
        "topup_allowed",
        "idr_cny_route",
        "posting_api",
    ):
        assert claims[key].support == "NOT_STATED"
        assert claims[key].value is None
    assert claims["transfer_references"].value == bundle.simulation.policy.required_references
    assert bundle.simulation.policy.posting_window_hours == 48
    assert not bundle.simulation.policy.partial_payment_allowed
    assert not bundle.simulation.policy.topup_allowed
    assert [link.claim_key for link in bundle.simulation.procedural_inspiration] == [
        "transfer_references"
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"support": "NOT_STATED", "value": False},
        {"support": "NOT_STATED", "value": "not allowed"},
        {"value": None},
        {"value": []},
        {"locator": ""},
        {"conditions": ""},
        {"approved": True},
    ],
)
def test_claim_rejects_invented_defaults_missing_evidence_and_authority(changes):
    claim = load_bundle().reference.claims[1].model_dump()
    with pytest.raises(ValidationError):
        Claim.model_validate(claim | changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"reviewed_on": "2026-08-07"},
        {"source_url": "https://iczu.zju.edu.cn.example.invalid/fake"},
        {"source_url": "http://iczu.zju.edu.cn/fake"},
        {"source_url": "https://untrusted@iczu.zju.edu.cn/fake"},
        {"payment_period": {"start": "2026-09-10", "end": "2026-08-10"}},
        {"synthetic": True},
        {"applicability": "CURRENT"},
    ],
)
def test_reference_rejects_invalid_provenance_or_unreviewed_applicability(changes):
    reference = load_bundle().reference.model_dump()
    with pytest.raises(ValidationError):
        ReviewedReference.model_validate(reference | changes)


def test_reference_rejects_duplicate_claims():
    reference = load_bundle().reference.model_dump()
    reference["claims"] += (reference["claims"][0],)
    with pytest.raises(ValidationError, match="unique"):
        ReviewedReference.model_validate(reference)


@pytest.mark.parametrize(
    "changes",
    [
        {"claim_key": "posting_window_hours"},
        {"reference_id": "unreviewed_source"},
        {"reference_revision": 2},
    ],
)
def test_bundle_rejects_unstated_or_wrong_revision_inspiration(changes):
    bundle = load_bundle().model_dump()
    link = bundle["simulation"]["procedural_inspiration"][0] | changes
    bundle["simulation"]["procedural_inspiration"] = [link]
    with pytest.raises(ValidationError, match="explicit claim"):
        KnowledgeBundle.model_validate(bundle)


@pytest.mark.parametrize(
    "changes",
    [
        {"university_id": "zju"},
        {"certainty": "UNKNOWN"},
        {"synthetic": False},
        {"source_url": str(load_bundle().reference.source_url)},
    ],
)
def test_simulation_cannot_masquerade_as_official_policy(changes):
    bundle = load_bundle().model_dump()
    bundle["simulation"]["policy"].update(changes)
    with pytest.raises(ValidationError):
        KnowledgeBundle.model_validate(bundle)


def test_bundled_data_is_sanitized_and_loader_returns_independent_records():
    for path in (Path("backend/kb/data")).glob("*.json"):
        raw = path.read_text(encoding="utf-8")
        json.loads(raw)
        assert not re.search(r"\b\d{10,}\b", raw)
        assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", raw)
        assert "Account Number" not in raw
        assert "Swift Code" not in raw
    first = load_bundle()
    second = load_bundle()
    assert first == second
    assert first is not second


@pytest.mark.parametrize("duplicate", ["record", "policy", "version"])
def test_simulation_variants_cannot_reuse_another_records_identity(duplicate):
    bundle = load_bundle().model_dump()
    variant = bundle["simulation_variants"][0]
    original = bundle["simulation"]
    if duplicate == "record":
        variant["id"] = original["id"]
    else:
        field = "id" if duplicate == "policy" else "version"
        variant["policy"][field] = original["policy"][field]
    with pytest.raises(ValidationError, match="must be unique"):
        KnowledgeBundle.model_validate(bundle)


def test_variant_cannot_activate_unreviewed_procedural_claims():
    bundle = load_bundle().model_dump()
    bundle["simulation_variants"][0]["procedural_inspiration"][0]["claim_key"] = "topup_allowed"
    with pytest.raises(ValidationError, match="explicit claim"):
        KnowledgeBundle.model_validate(bundle)


def test_unlisted_policy_files_cannot_enable_new_rules(tmp_path, monkeypatch):
    from backend.kb import catalog
    from backend.kb.guidance import known_policy

    for name in (
        "zju-current-students-2026-v1.json", "uni-cn-01-policy-v1.json",
        "uni-cn-01-policy-v1-topup.json",
    ):
        (tmp_path / name).write_bytes((Path("backend/kb/data") / name).read_bytes())
    unreviewed = POLICY.model_copy(update={"posting_window_hours": 1})
    (tmp_path / "downloaded-policy.json").write_text(unreviewed.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(catalog, "_DATA", tmp_path)
    assert not known_policy(unreviewed, catalog.load_bundle(), NOW)
