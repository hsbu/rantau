"""Rantau application skeleton: liveness, honest readiness, no fake authority."""

import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from backend.agent.router import router as agent_router
from backend.approvals.router import router as approval_router
from backend.authz.router import router as auth_router
from backend.config import Settings
from backend.demo.http import router as demo_router
from backend.finance.http import router as finance_router
from backend.fraud.router import router as security_router

app = FastAPI(title="Rantau", version="0.1.0")
app.include_router(agent_router)
app.include_router(auth_router)
app.include_router(finance_router)
app.include_router(demo_router)
app.include_router(approval_router)
app.include_router(security_router)


@app.get("/health")
async def health() -> dict[str, str | bool]:
    return {"status": "ok", "simulation": True}


async def database_available(settings: Settings) -> bool:
    if not settings.database_url:
        return False
    try:
        async with await psycopg.AsyncConnection.connect(
            settings.database_url.get_secret_value(), connect_timeout=3
        ) as connection:
            await connection.execute("SELECT 1")
        return True
    except psycopg.Error:
        return False


@app.get("/ready")
async def ready() -> JSONResponse:
    settings = Settings()
    dependencies = {
        "database": await database_available(settings),
        "authentication": await run_in_threadpool(authentication_ready, settings),
        "finance_storage": await run_in_threadpool(finance_storage_available, settings),
        "domain_services": False,
        "classifier_configuration": settings.classifier_configured,
    }
    return JSONResponse(
        status_code=503,
        content={
            "status": "not_ready",
            "simulation": True,
            "dependencies": dependencies,
        },
    )


def finance_storage_available(settings: Settings) -> bool:
    from backend.authz.storage import Database
    from backend.finance.wiring import finance_storage_ready

    if not settings.database_url:
        return False
    return finance_storage_ready(Database(settings.database_url.get_secret_value()))


def authentication_ready(settings: Settings) -> bool:
    from backend.authz.service import AuthService
    from backend.authz.storage import Database

    return bool(
        settings.auth_configured
        and settings.database_url
        and AuthService(
            Database(settings.database_url.get_secret_value()), settings.auth_tenant_id
        ).ready()
    )
