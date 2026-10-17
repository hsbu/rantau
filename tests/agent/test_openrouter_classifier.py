import json

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import SecretStr

from backend.agent.classifier import ClassificationUnavailable
from backend.agent.openrouter_classifier import OPENROUTER_BASE_URL, OpenRouterIntentClassifier
from backend.config import Settings


def response_body(content, finish_reason="stop", refusal=None):
    return {
        "id": "chat_fixture",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content, "refusal": refusal},
            }
        ],
    }


async def test_openrouter_transport_uses_configured_model_schema_and_redacts():
    requests = []

    def handler(request):
        assert str(request.url) == OPENROUTER_BASE_URL + "/chat/completions"
        requests.append(json.loads(request.content))
        return httpx.Response(
            200, json=response_body('{"intent":"TUITION","needs_clarification":false}')
        )

    client = AsyncOpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key="synthetic-test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    classifier = OpenRouterIntentClassifier(
        Settings(_env_file=None, openrouter_model="provider/configurable-model"), client
    )
    result = await classifier.classify(
        "Pay tuition. Account 123456789012, email a@test.invalid, sk-or-synthetic-key"
    )
    assert result.intent == "TUITION"
    payload = requests[0]
    assert payload["model"] == "provider/configurable-model"
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["provider"]["require_parameters"] is True
    assert payload["provider"]["data_collection"] == "deny"
    assert payload["messages"][0]["role"] == "system"
    content = payload["messages"][1]["content"]
    for private in ("123456789012", "a@test.invalid", "sk-or-synthetic-key", "actor_id"):
        assert private not in content
    await classifier.close()


@pytest.mark.parametrize("mode", ["refusal", "invalid", "http_error", "timeout", "incomplete"])
async def test_refusal_invalid_output_and_api_error_are_unavailable(mode):
    def handler(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("synthetic private timeout detail", request=request)
        if mode == "http_error":
            return httpx.Response(500, json={"error": {"message": "private provider error"}})
        return httpx.Response(
            200,
            json=response_body(
                '{"intent":"EXECUTE_NOW"}',
                finish_reason="length" if mode == "incomplete" else "stop",
                refusal="private refusal detail" if mode == "refusal" else None,
            ),
        )

    client = AsyncOpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key="synthetic-test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    classifier = OpenRouterIntentClassifier(
        Settings(_env_file=None, openrouter_model="provider/test-model"), client
    )
    with pytest.raises(ClassificationUnavailable, match="result is unavailable"):
        await classifier.classify("Tuition")
    await classifier.close()


async def test_missing_openrouter_config_never_uses_openai_key_or_fake(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-unused-key")
    monkeypatch.setenv("OPENAI_MODEL", "unused-model")
    settings = Settings(_env_file=None)
    assert not settings.classifier_configured
    classifier = OpenRouterIntentClassifier(settings)
    with pytest.raises(ClassificationUnavailable, match="configuration is unavailable"):
        await classifier.classify("Tuition")


async def test_real_client_targets_only_openrouter():
    classifier = OpenRouterIntentClassifier(
        Settings(
            _env_file=None,
            openrouter_api_key=SecretStr("synthetic-key"),
            openrouter_model="provider/test-model",
        )
    )
    assert str(classifier.client.base_url) == OPENROUTER_BASE_URL + "/"
    await classifier.close()
