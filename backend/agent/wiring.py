"""Default scoped reads and explicitly confirmed, protected tuition actions."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from backend.agent.actions import TuitionActions
from backend.agent.openrouter_classifier import OpenRouterIntentClassifier
from backend.agent.router import AgentServices
from backend.agent.services import durable_agent_services
from backend.agent.tools import AgentTools
from backend.approvals.finance_authority import StoredAuthority
from backend.approvals.wiring import build_approval_service
from backend.authz.service import AuthService
from backend.authz.storage import Database
from backend.contracts.models import ServiceUnavailable
from backend.dependencies import auth_settings
from backend.finance.ports import FinanceAgentReadPort
from backend.finance.reads import FinanceReads
from backend.finance.wiring import build_services, finance_storage_ready
from backend.university.port import ObligationReader


def storage_ready(database: Database) -> bool:
    if not finance_storage_ready(database):
        return False
    try:
        with database.connection() as connection:
            applied = connection.execute(
                "SELECT version FROM rantau_migrations WHERE version IN "
                "('020_agent_storage','021_agent_actions')"
            ).fetchall()
            connection.execute("SELECT run_id, metadata FROM agent_runs WHERE false")
            connection.execute(
                "SELECT action_key,intent_id,execution_key FROM agent_actions WHERE false"
            )
            connection.execute(
                "SELECT state, revision, scenario_run_no, expires_at "
                "FROM agent_conversations WHERE false"
            )
            return len(applied) == 2
    except ServiceUnavailable:
        return False


@asynccontextmanager
async def configured_agent_services(
    *, require_classifier: bool = True
) -> AsyncIterator[AgentServices]:
    settings = auth_settings()
    if require_classifier and not settings.classifier_configured:
        raise HTTPException(503, detail={"code": "CLASSIFIER_NOT_CONFIGURED"})
    assert settings.database_url is not None
    database = Database(settings.database_url.get_secret_value())
    if not await run_in_threadpool(storage_ready, database):
        raise HTTPException(503, detail={"code": "AGENT_STORAGE_UNAVAILABLE"})
    auth = AuthService(database, settings.auth_tenant_id)
    obligations = ObligationReader(database, auth)
    reads = FinanceReads(database, auth, obligations)
    tools = AgentTools(
        FinanceAgentReadPort(reads, obligations),
        # Fixed fictional university binding; never supplied by chat/model/web content.
        beneficiary_map={"uni_cn_01": "benef_uni_cn_01"},
    )
    classifier = OpenRouterIntentClassifier(settings)
    try:
        finance = build_services(database, auth, StoredAuthority(settings.auth_tenant_id))
        actions = TuitionActions(
            finance, build_approval_service(auth, settings.approval_ttl_seconds)
        )
        yield durable_agent_services(database, auth, classifier, tools, actions)
    finally:
        await classifier.close()
