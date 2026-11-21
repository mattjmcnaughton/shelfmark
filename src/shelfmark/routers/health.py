"""Health check endpoints."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@router.get("/readyz", response_model=None)
async def readyz(request: Request) -> dict[str, str] | JSONResponse:
    """Readiness probe: the database answers."""
    try:
        async with request.app.state.database.session() as session:
            await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        return JSONResponse({"status": "not ready", "database": "unreachable"}, 503)
    return {"status": "ready"}
