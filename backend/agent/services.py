"""Explicit construction from trusted adapters; no default HTTP dependency override."""

from backend.agent.classifier import IntentClassifier
from backend.agent.graph import AgentGraph
from backend.agent.persistence import PostgresConversations, PostgresRuns
from backend.agent.router import AgentServices
from backend.agent.tools import AgentTools
from backend.authz.service import AuthService
from backend.authz.storage import Database


def durable_agent_services(
    database: Database,
    auth: AuthService,
    classifier: IntentClassifier,
    tools: AgentTools,
) -> AgentServices:
    """The application integrator supplies real scoped domain tools and verified auth."""
    return AgentServices(
        AgentGraph(classifier, tools, conversations=PostgresConversations(database, auth)),
        PostgresRuns(database, auth),
    )
