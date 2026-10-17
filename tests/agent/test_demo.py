from unittest.mock import AsyncMock

import pytest

from backend.agent import demo
from backend.agent.state import TuitionInput
from tests.agent.test_tuition import Turns


async def test_live_runner_preserves_conversation_and_closes_client(monkeypatch, capsys):
    class Configured:
        classifier_configured = True

    classifier = Turns(TuitionInput(), TuitionInput())
    classifier.close = AsyncMock()
    monkeypatch.setattr(demo, "Settings", Configured)
    monkeypatch.setattr(demo, "OpenRouterIntentClassifier", lambda settings: classifier)
    await demo.live_demo(["Pay tuition", "Continue"])
    assert "Draft intent preview" in capsys.readouterr().out
    assert "Prior intent: TUITION" in classifier.prompts[1]
    classifier.close.assert_awaited_once()


async def test_live_runner_requires_explicit_provider_configuration(monkeypatch):
    class Missing:
        classifier_configured = False

    monkeypatch.setattr(demo, "Settings", Missing)
    with pytest.raises(SystemExit, match="OPENROUTER_API_KEY"):
        await demo.live_demo(["Tuition"])
