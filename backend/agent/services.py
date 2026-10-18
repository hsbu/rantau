"""Explicit construction from trusted adapters; no default HTTP dependency override."""

from backend.agent.actions import TuitionActions
from backend.agent.classifier import IntentClassifier
from backend.agent.graph import AgentGraph
from backend.agent.persistence import PostgresConversations, PostgresRuns
from backend.agent.recovery import RecoveryWorkflow
from backend.agent.router import AgentServices
from backend.agent.tools import AgentTools
from backend.authz.service import AuthService
from backend.authz.storage import Database


def durable_agent_services(
    database: Database,
    auth: AuthService,
    classifier: IntentClassifier,
    tools: AgentTools,
    actions: TuitionActions | None = None,
    recovery: RecoveryWorkflow | None = None,
) -> AgentServices:
    """The application integrator supplies real scoped domain tools and verified auth."""
    return AgentServices(
        AgentGraph(
            classifier,
            tools,
            conversations=PostgresConversations(database, auth),
            actions=actions,
            recovery=recovery,
        ),
        PostgresRuns(database, auth),
    )
