import json

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import SecretStr

from backend.agent.classifier import ClassificationUnavailable
from backend.agent.openai_classifier import OpenAIIntentClassifier
from backend.config import Settings


def response_body(output):
    return {
        "id": "resp_fixture",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": "test-model",
        "output": [
            {
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": output,
            }
        ],
        "parallel_tool_calls": False,
        "tools": [],
        "tool_choice": "auto",
    }


async def test_structured_openai_transport_uses_configured_model_and_redacts():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json=response_body(
                [
                    {
                        "type": "output_text",
                        "text": '{"intent":"TUITION","needs_clarification":false}',
                        "annotations": [],
                    }
                ]
            ),
        )

    client = AsyncOpenAI(
        api_key="synthetic-test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    settings = Settings(
        _env_file=None,
        openai_model="configurable-test-model",
        openai_api_key=SecretStr("synthetic-test-key"),
    )
    classifier = OpenAIIntentClassifier(settings, client)
    result = await classifier.classify(
        "Pay tuition. My account is 123456789012, email a@test.invalid"
    )
    assert result.intent == "TUITION"
    payload = requests[0]
    assert payload["model"] == "configurable-test-model"
    assert payload["store"] is False
    assert payload["text"]["format"]["type"] == "json_schema"
    assert "123456789012" not in payload["input"]
    assert "a@test.invalid" not in payload["input"]
    assert "actor_id" not in payload["input"]
    await classifier.close()


@pytest.mark.parametrize("mode", ["refusal", "invalid", "http_error", "timeout", "incomplete"])
async def test_refusal_invalid_output_and_api_error_are_unavailable(mode):
    def handler(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("synthetic private timeout detail", request=request)
        if mode == "http_error":
            return httpx.Response(500, json={"error": {"message": "secret provider error"}})
        content = (
            [{"type": "refusal", "refusal": "private refusal detail"}]
            if mode == "refusal"
            else [{"type": "output_text", "text": '{"intent":"EXECUTE_NOW"}', "annotations": []}]
        )
        body = response_body(content)
        if mode == "incomplete":
            body["status"] = "incomplete"
        return httpx.Response(200, json=body)

    client = AsyncOpenAI(
        api_key="synthetic-test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    classifier = OpenAIIntentClassifier(Settings(_env_file=None, openai_model="test-model"), client)
    with pytest.raises(ClassificationUnavailable, match="result is unavailable"):
        await classifier.classify("Tuition")
    await classifier.close()


async def test_no_key_or_model_does_not_fall_back_to_a_fake(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    classifier = OpenAIIntentClassifier(Settings(_env_file=None))
    with pytest.raises(ClassificationUnavailable, match="configuration is unavailable"):
        await classifier.classify("Tuition")
