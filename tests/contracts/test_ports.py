import pytest

from backend.contracts.models import IntentProposal, ServiceUnavailable
from backend.contracts.ports import (
    AgentReadPort,
    AuthorizationPort,
    PaymentPort,
    ProposalPort,
    UniversityPort,
)
from tests.fixtures.data import ACTOR
from tests.fixtures.fakes import (
    FakeAuthorizationPort,
    FakePaymentPort,
    FakeProposalPort,
    FakeReadPort,
    FakeUniversityPort,
)


async def test_contract_smoke_requests_approval_and_cannot_fake_execution():
    proposals: ProposalPort = FakeProposalPort()
    reads: AgentReadPort = FakeReadPort()
    gate: AuthorizationPort = FakeAuthorizationPort()
    payments: PaymentPort = FakePaymentPort()
    university: UniversityPort = FakeUniversityPort()
    assert reads and gate and university
    result = await proposals.create_intent(
        IntentProposal(
            obligation_id="obl_2026_demo_01",
            source_account_id="acct_idr_01",
            beneficiary_id="benef_uni_cn_01",
            quote_id="quote_001",
            purpose="TUITION",
        ),
        ACTOR,
    )
    assert result.data.state == "AWAITING_APPROVAL"
    request = await proposals.request_approval(result.data.id, ACTOR)
    assert request.state == "AWAITING_APPROVAL"
    with pytest.raises(ServiceUnavailable):
        await payments.execute(result.data.id, "stable-key", ACTOR)


def test_export_has_full_catalogue_and_no_actor_request():
    from backend.contracts.schema import contract_schema

    schema = contract_schema()
    assert len(schema["paths"]) == 40
    assert schema["paths"]["/api/v1/security-cases"]["get"]["x-owner"] == "B"
    execution = schema["paths"]["/api/v1/payment-intents/{id}/execute"]["post"]
    assert any(p["name"] == "Idempotency-Key" for p in execution["parameters"])
    request = schema["components"]["schemas"]["AgentMessage"]
    assert "actor_id" not in request["properties"]
    assert request["additionalProperties"] is False


def test_auth_contracts_are_additive_and_preserve_both_consent_methods():
    from backend.contracts.schema import contract_schema

    schema = contract_schema()
    login = schema["paths"]["/api/v1/auth/login"]["post"]
    assert login["security"] == []
    assert login["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/LoginRequest"
    )
    assert set(schema["paths"]["/api/v1/student/sharing-consents/{sponsor_id}"]) == {
        "put",
        "delete",
    }
    assert "content" not in schema["paths"]["/api/v1/auth/logout"]["post"]["responses"]["204"]
