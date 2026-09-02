from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from multi_domain_enterprise_project.core.auth import CurrentUser, require_permissions
from multi_domain_enterprise_project.core.database import (
    IngestionJobRecord,
    KnowledgeDocumentRecord,
    get_session,
)
from multi_domain_enterprise_project.core.jobs import DEAD_LETTER_STREAM, JOB_GROUP, JOB_STREAM

router = APIRouter(prefix="/api/platform/runtime/worker", tags=["platform-worker"])
Session = Annotated[AsyncSession, Depends(get_session)]
PlatformReader = Annotated[CurrentUser, Depends(require_permissions("audit:read", "kb:read"))]


class WorkerConsumer(BaseModel):
    name: str
    pending: int
    idle_ms: int
    inactive_ms: int | None = None


class QueueSnapshot(BaseModel):
    available: bool
    group_initialized: bool = False
    stream_length: int = 0
    dead_letter_length: int = 0
    pending: int = 0
    lag: int | None = None
    consumers: list[WorkerConsumer] = Field(default_factory=list)
    error: str | None = None


class WorkerJob(BaseModel):
    id: str
    document_id: str
    file_name: str | None = None
    operation: str
    mode: str
    status: str
    attempts: int
    updated_at: str


class WorkerStatusCount(BaseModel):
    status: str
    count: int


class WorkerRuntimeSnapshot(BaseModel):
    checked_at: str
    stream_name: str = JOB_STREAM
    dead_letter_stream_name: str = DEAD_LETTER_STREAM
    group_name: str = JOB_GROUP
    queue: QueueSnapshot
    status_counts: list[WorkerStatusCount]
    active_jobs: list[WorkerJob]
    worker_max_attempts: int
    worker_block_ms: int
    heartbeat_available: bool = False
    observation_note: str = "Redis 消费者注册和 idle 不是独立心跳，不能单独证明 Worker 存活。"


async def _read_queue_snapshot() -> QueueSnapshot:
    redis = Redis.from_url(settings.llm_key.redis, decode_responses=True)
    try:
        stream_length = int(await redis.xlen(JOB_STREAM))
        dead_letter_length = int(await redis.xlen(DEAD_LETTER_STREAM))
        groups = await redis.xinfo_groups(JOB_STREAM)
        group = next((item for item in groups if item.get("name") == JOB_GROUP), None)
        if group is None:
            return QueueSnapshot(
                available=True,
                stream_length=stream_length,
                dead_letter_length=dead_letter_length,
            )
        try:
            raw_consumers = await redis.xinfo_consumers(JOB_STREAM, JOB_GROUP)
        except ResponseError:
            raw_consumers = []
        consumers = []
        for item in raw_consumers:
            inactive = int(item.get("inactive", -1))
            consumers.append(WorkerConsumer(
                name=str(item.get("name") or "unknown"),
                pending=int(item.get("pending", 0)),
                idle_ms=int(item.get("idle", 0)),
                inactive_ms=inactive if inactive >= 0 else None,
            ))
        return QueueSnapshot(
            available=True,
            group_initialized=True,
            stream_length=stream_length,
            dead_letter_length=dead_letter_length,
            pending=int(group.get("pending", 0)),
            lag=int(group["lag"]) if group.get("lag") is not None else None,
            consumers=consumers,
        )
    except Exception as exc:
        return QueueSnapshot(
            available=False,
            error=f"{type(exc).__name__}: Redis 队列状态读取失败",
        )
    finally:
        await redis.aclose()


@router.get("", response_model=WorkerRuntimeSnapshot)
async def get_worker_runtime(current_user: PlatformReader, session: Session) -> WorkerRuntimeSnapshot:
    queue = await _read_queue_snapshot()
    status_rows = (
        await session.execute(
            select(IngestionJobRecord.status, func.count())
            .where(IngestionJobRecord.tenant_id == current_user.tenant_id)
            .group_by(IngestionJobRecord.status)
            .order_by(IngestionJobRecord.status)
        )
    ).all()
    active_rows = (
        await session.execute(
            select(IngestionJobRecord, KnowledgeDocumentRecord.file_name)
            .outerjoin(
                KnowledgeDocumentRecord,
                and_(
                    KnowledgeDocumentRecord.id == IngestionJobRecord.document_id,
                    KnowledgeDocumentRecord.tenant_id == IngestionJobRecord.tenant_id,
                ),
            )
            .where(
                IngestionJobRecord.tenant_id == current_user.tenant_id,
                IngestionJobRecord.status.in_(("queued", "processing")),
            )
            .order_by(IngestionJobRecord.updated_at.asc())
            .limit(20)
        )
    ).all()
    return WorkerRuntimeSnapshot(
        checked_at=datetime.now(UTC).isoformat(),
        queue=queue,
        status_counts=[WorkerStatusCount(status=str(name), count=int(count)) for name, count in status_rows],
        active_jobs=[WorkerJob(
            id=job.id,
            document_id=job.document_id,
            file_name=file_name,
            operation=job.operation,
            mode=job.mode,
            status=job.status,
            attempts=job.attempts,
            updated_at=job.updated_at.isoformat(),
        ) for job, file_name in active_rows],
        worker_max_attempts=settings.runtime.worker_max_attempts,
        worker_block_ms=settings.runtime.worker_block_ms,
    )
