"""Offline loading of fixed, reviewed records; no scraping or automatic activation."""

from pathlib import Path

from backend.kb.records import KnowledgeBundle, ReviewedReference, SimulationPolicy

_DATA = Path(__file__).parent / "data"


def load_bundle() -> KnowledgeBundle:
    """Validate provenance links without installing any policy or authorization adapter."""
    reference = ReviewedReference.model_validate_json(
        (_DATA / "zju-current-students-2026-v1.json").read_text(encoding="utf-8")
    )
    simulation = SimulationPolicy.model_validate_json(
        (_DATA / "uni-cn-01-policy-v1.json").read_text(encoding="utf-8")
    )
    return KnowledgeBundle(reference=reference, simulation=simulation)
