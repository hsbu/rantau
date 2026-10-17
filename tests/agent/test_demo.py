from unittest.mock import AsyncMock

import httpx
import pytest

from backend.agent import demo
from backend.agent.state import TuitionInput
from backend.contracts.enums import Intent
from backend.kb.research import OfficialSourceLookup
from tests.agent.test_graph import FixedClassifier
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


async def test_live_runner_opt_in_wires_public_lookup(monkeypatch, capsys):
    class Configured:
        classifier_configured = True

    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<p>Shortfall</p>")

    lookup = OfficialSourceLookup(transport=httpx.MockTransport(handler))
    classifier = FixedClassifier(Intent.ASK_POLICY)
    classifier.close = AsyncMock()
    monkeypatch.setattr(demo, "Settings", Configured)
    monkeypatch.setattr(demo, "OpenRouterIntentClassifier", lambda settings: classifier)
    monkeypatch.setattr(demo, "OfficialSourceLookup", lambda: lookup)
    await demo.live_demo(["Explain tuition policy"], web_guidance=True)
    output = capsys.readouterr().out
    assert len(requests) == 2
    assert "pending university review" in output
    assert "possible shortfall-related text" in output
    classifier.close.assert_awaited_once()
