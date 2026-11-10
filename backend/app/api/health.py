from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    """Unprefixed, outside /api/v1 -- an infra-level probe (Docker/compose
    healthcheck), not a versioned API resource. Checks real DB connectivity,
    never a mock, consistent with docs/09-TESTING-STRATEGY.md's philosophy."""
    try:
        await db.execute(text("SELECT 1"))
        database_status = "connected"
    except Exception:
        database_status = "unreachable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if database_status == "connected" else "degraded",
        "database": database_status,
    }
