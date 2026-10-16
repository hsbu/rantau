"""Rantau application skeleton: liveness, honest readiness, no fake authority."""

import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from backend.config import Settings

app = FastAPI(title="Rantau", version="0.1.0")


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
        "authentication": False,
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
