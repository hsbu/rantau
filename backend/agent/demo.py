"""Explicit offline harness, never imported by the running application."""

import argparse
import asyncio
import json

from backend.agent.classifier import IntentClassification
from backend.agent.graph import AgentGraph
from backend.agent.openrouter_classifier import OpenRouterIntentClassifier
from backend.agent.tools import AgentTools
from backend.config import Settings
from backend.contracts.enums import Intent
from backend.kb.research import OfficialSourceLookup, explain_research


class DemoClassifier:
    """Forced classification for six deterministic smoke turns, not an NLP model."""

    def __init__(self, intent: Intent) -> None:
        self.intent = intent

    async def classify(self, message: str) -> IntentClassification:
        return IntentClassification(intent=self.intent, needs_clarification=False)


async def demo() -> None:
    # Local test fixtures are imported only after the caller explicitly selects this harness.
    from tests.fixtures.data import ACTOR, NOW
    from tests.fixtures.fakes import FakeReadPort

    for intent in Intent:
        graph = AgentGraph(
            DemoClassifier(intent),
            AgentTools(
                FakeReadPort(),
                clock=lambda: NOW,
                beneficiary_map={"uni_cn_01": "benef_uni_cn_01"},
            ),
        )
        result = await graph.run("Review transfer_001", ACTOR)
        print(
            json.dumps(
                {
                    "simulation": True,
                    "classifier": "forced offline fixture",
                    "intent": intent.value,
                    "response": result.model_dump(mode="json"),
                }
            )
        )


async def live_demo(messages: list[str], *, web_guidance: bool = False) -> None:
    """Explicit local harness: live interpretation, synthetic reads, no financial execution."""
    from tests.fixtures.data import ACTOR, NOW
    from tests.fixtures.fakes import FakeReadPort

    settings = Settings()
    if not settings.classifier_configured:
        raise SystemExit("Set OPENROUTER_API_KEY and OPENROUTER_MODEL locally first.")
    if any(not message.strip() or len(message) > 4000 for message in messages):
        raise SystemExit("Use between 1 and 4000 characters per turn.")
    classifier = OpenRouterIntentClassifier(settings)
    graph = AgentGraph(
        classifier,
        AgentTools(
            FakeReadPort(),
            clock=lambda: NOW,
            beneficiary_map={"uni_cn_01": "benef_uni_cn_01"},
            research=OfficialSourceLookup() if web_guidance else None,
        ),
    )
    print(
        "Local synthetic scenario; live OpenRouter interpretation. No payment execution. "
        "Conversation drafts reset when this runner exits. Type /quit to exit."
    )
    try:
        if messages:
            for message in messages:
                result = await graph.run(message, ACTOR, "interactive_demo")
                print(result.message)
            return
        while True:
            try:
                message = await asyncio.to_thread(input, "You: ")
            except EOFError:
                break
            if message.strip().lower() == "/quit":
                break
            if not message.strip():
                continue
            if len(message) > 4000:
                print("Use at most 4000 characters per turn.")
                continue
            result = await graph.run(message, ACTOR, "interactive_demo")
            print("Rantau: " + result.message)
    finally:
        await classifier.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Rantau isolated synthetic agent smoke demo")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fake-classifier", action="store_true")
    mode.add_argument("--openrouter", action="store_true")
    mode.add_argument(
        "--research-shortfall",
        action="store_true",
        help="Read curated official sources without a model or private financial data",
    )
    parser.add_argument(
        "--web-guidance", action="store_true", help="Enable official-source reads in live demo"
    )
    parser.add_argument(
        "--message", action="append", default=[], help="Repeat for multi-turn input"
    )
    args = parser.parse_args()
    if args.message and not args.openrouter:
        parser.error("--message requires --openrouter")
    if args.web_guidance and not args.openrouter:
        parser.error("--web-guidance requires --openrouter")
    if args.research_shortfall:
        result = asyncio.run(OfficialSourceLookup().lookup())
        print(explain_research(result))
    else:
        asyncio.run(
            live_demo(args.message, web_guidance=args.web_guidance) if args.openrouter else demo()
        )


if __name__ == "__main__":
    main()
