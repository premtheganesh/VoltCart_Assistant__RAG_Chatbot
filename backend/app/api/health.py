"""Health check: is the API up, can it reach Postgres, is pgvector installed?"""

import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.db.session import DbSession

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health")
def health(response: Response, session: DbSession) -> dict:
    try:
        session.execute(text("SELECT 1"))
        pgvector = session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
    except Exception:
        logger.exception("Database health check failed")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "db": "unreachable", "pgvector": None}

    return {"status": "ok", "db": "ok", "pgvector": pgvector or "missing"}
