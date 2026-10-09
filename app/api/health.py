import asyncio
import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.schemas import ErrorResponse
from app.infrastructure.db.session import engine

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/ready",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": "Database unavailable",
        }
    },
)
async def ready() -> dict[str, str]:
    try:
        await asyncio.wait_for(_database_ready(), timeout=2)
    except (TimeoutError, SQLAlchemyError) as exc:
        logger.warning("Readiness check failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc
    return {"status": "ok"}


async def _database_ready() -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
