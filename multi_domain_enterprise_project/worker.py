from __future__ import annotations

import asyncio
import logging
import os
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis

from config import settings, validate_runtime_settings
from multi_domain_enterprise_project.core.database import (
    IngestionJobRecord,
    SessionFactory,
    close_database,
    get_document,
    init_database,
    remove_document_record,
    update_document,
    update_job,
)
from multi_domain_enterprise_project.core.jobs import (
    DEAD_LETTER_STREAM,
    JOB_GROUP,
    JOB_STREAM,
    decode_job,
    enqueue_job,
    ensure_job_group,
)
from multi_domain_enterprise_project.core.observability import INGESTION_JOBS, configure_logging
from multi_domain_enterprise_project.core.storage import parsed_document_path, remove_storage_path
from multi_domain_enterprise_project.rag.rag_service import delete_document_data, insert_service

configure_logging()
logger = logging.getLogger(__name__)
JobOperation = Callable[[dict[str, Any], str], Awaitable[None]]


@dataclass(frozen=True)
class StreamMessage:
    message_id: str
    fields: dict[str, str]


def _backend_success(mode: str) -> dict[str, str]:
    names = {"milvus": ["milvus"], "graph": ["neo4j"], "mg": ["milvus", "neo4j"]}[mode]
    return {name: "success" for name in names}


async def _ingest_document(item: dict[str, Any], mode: str) -> None:
    chunk_count = await insert_service(
        file_path=item["file_path"],
        tenant_id=item["tenant_id"],
        user_id=item["owner_id"],
        title=item["title"],
        acl=item["acl"],
        mode=mode,
        document_id=item["id"],
        version=item["version"],
    )
    async with SessionFactory() as session:
        await update_document(
            session,
            item["id"],
            item["tenant_id"],
            status="ready",
            chunk_count=chunk_count,
            backend_status=_backend_success(mode),
            file_path_md=str(parsed_document_path(item["tenant_id"], item["id"])),
            error=None,
            ingest_progress=1,
            ingest_total=1,
            ingest_message="入库完成",
        )


async def _delete_document(item: dict[str, Any], mode: str) -> None:
    if item["chunk_count"] > 0 or item["backend_status"]:
        await delete_document_data(item["tenant_id"], item["id"], mode=mode)
    remove_storage_path(item.get("file_path_md") or str(parsed_document_path(item["tenant_id"], item["id"])))
    remove_storage_path(item.get("file_path"))
    async with SessionFactory() as session:
        removed = await remove_document_record(session, item["id"], item["tenant_id"])
        if not removed:
            raise RuntimeError("文档元数据已不存在")


OPERATIONS: dict[str, JobOperation] = {
    "ingest": _ingest_document,
    "delete": _delete_document,
}


async def _record_failure(redis: Redis, message: StreamMessage, job: dict[str, str], error: Exception) -> None:
    attempts = int(job["attempts"]) + 1
    error_message = f"{type(error).__name__}: {error}"[:2000]
    document_status = "delete_failed" if job["operation"] == "delete" else "failed"
    async with SessionFactory() as session:
        if attempts >= settings.runtime.worker_max_attempts:
            await update_job(session, job["job_id"], status="failed", attempts=attempts, error=error_message)
            await update_document(
                session,
                job["document_id"],
                job["tenant_id"],
                status=document_status,
                error=error_message,
                ingest_message="任务重试耗尽",
            )
            await redis.xadd(DEAD_LETTER_STREAM, {**job, "attempts": str(attempts), "error": error_message})
            INGESTION_JOBS.labels(operation=job["operation"], status="dead_letter").inc()
        else:
            await update_job(session, job["job_id"], status="queued", attempts=attempts, error=error_message)
            await update_document(
                session,
                job["document_id"],
                job["tenant_id"],
                status="delete_queued" if job["operation"] == "delete" else "queued",
                error=error_message,
                ingest_message=f"等待第 {attempts + 1} 次执行",
            )
            await enqueue_job(
                redis,
                job_id=job["job_id"],
                document_id=job["document_id"],
                tenant_id=job["tenant_id"],
                operation=job["operation"],
                mode=job["mode"],
                attempts=attempts,
            )
            INGESTION_JOBS.labels(operation=job["operation"], status="retry").inc()
    await redis.xack(JOB_STREAM, JOB_GROUP, message.message_id)


async def process_message(redis: Redis, message: StreamMessage) -> None:
    try:
        job = decode_job(message.fields)
    except ValueError as exc:
        await redis.xadd(DEAD_LETTER_STREAM, {**message.fields, "error": str(exc)})
        await redis.xack(JOB_STREAM, JOB_GROUP, message.message_id)
        INGESTION_JOBS.labels(operation="invalid", status="dead_letter").inc()
        return

    try:
        operation = OPERATIONS[job["operation"]]
        async with SessionFactory() as session:
            record = await session.get(IngestionJobRecord, job["job_id"])
            if record is None:
                raise RuntimeError("任务元数据不存在")
            if record.status == "succeeded":
                await redis.xack(JOB_STREAM, JOB_GROUP, message.message_id)
                return
            item = await get_document(session, job["document_id"], job["tenant_id"])
            if item is None:
                raise RuntimeError("文档元数据不存在")
            await update_job(session, job["job_id"], status="processing", error=None)
            await update_document(
                session,
                job["document_id"],
                job["tenant_id"],
                status="deleting" if job["operation"] == "delete" else "processing",
                ingest_message="Worker 正在执行",
            )
        await operation(item, job["mode"])
        if job["operation"] != "delete":
            async with SessionFactory() as session:
                await update_job(
                    session,
                    job["job_id"],
                    status="succeeded",
                    attempts=int(job["attempts"]) + 1,
                    error=None,
                )
        await redis.xack(JOB_STREAM, JOB_GROUP, message.message_id)
        INGESTION_JOBS.labels(operation=job["operation"], status="succeeded").inc()
    except Exception as exc:
        logger.exception("任务执行失败", extra={"job_id": job["job_id"], "operation": job["operation"]})
        await _record_failure(redis, message, job, exc)


async def run_worker() -> None:
    validate_runtime_settings(settings)
    await init_database()
    redis = Redis.from_url(settings.llm_key.redis, decode_responses=True)
    consumer = f"{socket.gethostname()}-{os.getpid()}"
    try:
        await redis.ping()
        await ensure_job_group(redis)
        logger.info("任务 Worker 已启动", extra={"consumer": consumer})
        while True:
            streams = await redis.xreadgroup(
                JOB_GROUP,
                consumer,
                {JOB_STREAM: ">"},
                count=1,
                block=settings.runtime.worker_block_ms,
            )
            for _, messages in streams:
                for message_id, fields in messages:
                    await process_message(redis, StreamMessage(str(message_id), fields))
    finally:
        await redis.aclose()
        await close_database()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
