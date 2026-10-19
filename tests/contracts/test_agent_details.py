"""Safe presentation contracts exclude internal identifiers and inconsistent money."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.contracts.agent_details import AgentDetailSnapshot


def fixture():
    return json.loads(
        (Path(__file__).parents[2] / "frontend/tests/chat-detail-fixture.json").read_text(
            encoding="utf-8"
        )
    )


def test_shared_browser_fixture_validates_against_the_versioned_backend_projection():
    assert (
        AgentDetailSnapshot.model_validate(fixture()).summary.quote.source_total_minor == 46_025_000
    )


@pytest.mark.parametrize(
    "section,field",
    [
        ("obligation", "student_id"),
        ("quote", "id"),
        (None, "source_account_id"),
        (None, "terms_hash"),
    ],
)
def test_private_fields_are_rejected_instead_of_silently_dropped(section, field):
    data = fixture()
    target = data["summary"][section] if section else data["summary"]
    target[field] = "private_reference"
    with pytest.raises(ValidationError):
        AgentDetailSnapshot.model_validate(data)


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("obligation", "balance_minor", 1),
        ("obligation", "state", "PAID"),
        ("quote", "source_total_minor", 46_000_000),
        ("quote", "destination_amount_minor", 1),
        ("quote", "fee_minor", 25_000.0),
        ("quote", "fee_minor", True),
    ],
)
def test_inconsistent_or_inexact_display_amounts_fail_closed(section, field, value):
    data = fixture()
    data["summary"][section][field] = value
    with pytest.raises(ValidationError):
        AgentDetailSnapshot.model_validate(data)
