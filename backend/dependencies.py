"""Fail-closed integration seams for Dev B authentication and Dev C services."""

from fastapi import HTTPException

from backend.contracts.models import ActorContext


async def verified_actor() -> ActorContext:
    """Dev B replaces this with a server-verified session dependency."""
    raise HTTPException(
        status_code=503,
        detail={
            "code": "AUTHENTICATION_NOT_CONFIGURED",
            "message": "Authenticated sessions are not connected yet.",
        },
    )
