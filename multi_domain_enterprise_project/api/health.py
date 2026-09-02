from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from multi_domain_enterprise_project.core.database import SessionFactory
from multi_domain_enterprise_project.healthcheck import run_checks

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health/live")
async def liveness():
    return {"status": "ok"}


async def _readiness_payload(request: Request) -> tuple[bool, dict[str, Any]]:
    checks: dict[str, Any] = {}
    redis = getattr(request.app.state, "redis", None)
    try:
        checks["redis"] = bool(redis and await redis.ping())
    except Exception:
        checks["redis"] = False
    try:
        async with SessionFactory() as session:
            checks["database"] = (await session.execute(text("SELECT 1"))).scalar_one() == 1
    except Exception:
        checks["database"] = False
    checks["checkpointer"] = getattr(request.app.state, "checkpointer", None) is not None
    external = await run_checks({"milvus", "neo4j", "ollama", "mcp-rag"})
    checks.update({result.name: result.ok for result in external})
    return all(checks.values()), checks


@router.get("/health/ready")
@router.get("/health")
async def readiness(request: Request):
    ready, checks = await _readiness_payload(request)
    return JSONResponse(
        status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "ok" if ready else "not_ready", "checks": checks},
    )
