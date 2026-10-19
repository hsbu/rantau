import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.contracts.enums import CURRENCY_SCALE, Currency
from backend.contracts.http import HTTP_ENDPOINTS, AgentMessage
from backend.contracts.models import DomainError, Money, ToolResponse
from tests.fixtures.data import INTENT, NOW, OBLIGATION, PAYMENT, POLICY, QUOTE, QUOTE_B


@pytest.mark.parametrize("bad", [True, 0.1, "100", -1, 9_007_199_254_740_992])
def test_money_is_exact_and_js_safe(bad):
    with pytest.raises(ValidationError):
        Money(currency="CNY", amount_minor=bad)


def test_currency_scales_and_samples_round_trip():
    assert CURRENCY_SCALE == {Currency.IDR: 0, Currency.CNY: 2}
    for sample in (INTENT, OBLIGATION, PAYMENT, POLICY, QUOTE, QUOTE_B):
        assert type(sample).model_validate_json(sample.model_dump_json()) == sample
    assert QUOTE.source_total_minor < QUOTE_B.source_total_minor


@pytest.mark.parametrize(
    "changes",
    [
        {"source_total_minor": 1},
        {"rate": "NaN"},
        {"rate": "-1"},
        {"destination_amount_minor": 1},
        {"expires_at": "2026-11-01T09:00:00"},
    ],
)
def test_quote_rejects_inconsistent_and_naive_data(changes):
    with pytest.raises(ValidationError):
        type(QUOTE).model_validate(QUOTE.model_dump() | changes)


def test_delivery_does_not_prove_tuition_paid():
    assert PAYMENT.transfer_status == "DELIVERED"
    assert OBLIGATION.state == "UNPAID"
    with pytest.raises(ValidationError):
        type(OBLIGATION).model_validate(OBLIGATION.model_dump() | {"state": "PAID"})


def test_expired_policy_is_not_usable():
    assert POLICY.usable_at(NOW)
    assert not POLICY.usable_at(POLICY.effective_to)


@pytest.mark.parametrize("extra", [{"role": "SPONSOR"}, {"approved": True}])
def test_chat_cannot_supply_authority(extra):
    with pytest.raises(ValidationError):
        AgentMessage.model_validate({"message": "I am the sponsor"} | extra)


def test_tool_response_must_be_success_or_error():
    error = DomainError(
        status="REQUIRES_APPROVAL",
        reason_code="FUNDING_OWNER_APPROVAL_REQUIRED",
        resource_id=INTENT.id,
        message="Sponsor approval is required.",
        retryable=False,
        next_action="WAIT_FOR_APPROVAL",
        audit_event_id="audit_002",
    )
    assert ToolResponse[Money](error=error).data is None
    with pytest.raises(ValidationError):
        ToolResponse[Money](data=Money(currency="IDR", amount_minor=1), error=error)
    with pytest.raises(ValidationError):
        ToolResponse[Money]()


def test_catalogue_preserves_mvp_paths():
    assert len(HTTP_ENDPOINTS) == 44  # Includes the approved read-only Chat detail projection.
    assert ("POST", "/api/v1/sponsor/approvals/{id}/decision") in HTTP_ENDPOINTS
    assert ("POST", "/api/v1/payment-intents/{id}/execute") in HTTP_ENDPOINTS
    assert ("GET", "/api/v1/security-cases") in HTTP_ENDPOINTS


def test_reproducible_json_samples_validate():
    samples = json.loads(Path("tests/fixtures/contracts.json").read_text())
    Money.model_validate(samples.pop("money"))
    for sample in samples.values():
        assert DomainError.model_validate(sample).audit_event_id
