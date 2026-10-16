"""Explicit offline harness, never imported by the running application."""

import argparse
import asyncio
import json

from backend.agent.classifier import IntentClassification
from backend.agent.graph import AgentGraph
from backend.agent.tools import AgentTools
from backend.contracts.enums import Intent


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
        graph = AgentGraph(DemoClassifier(intent), AgentTools(FakeReadPort(), clock=lambda: NOW))
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Rantau isolated synthetic agent smoke demo")
    parser.add_argument("--fake-classifier", action="store_true", required=True)
    parser.parse_args()
    asyncio.run(demo())


if __name__ == "__main__":
    main()
