from __future__ import annotations

from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

JOB_STREAM = "rag:jobs"
DEAD_LETTER_STREAM = "rag:jobs:dead-letter"
JOB_GROUP = "rag-workers"


async def ensure_job_group(redis: Redis) -> None:
    try:
        await redis.xgroup_create(JOB_STREAM, JOB_GROUP, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def enqueue_job(
    redis: Redis,
    *,
    job_id: str,
    document_id: str,
    tenant_id: str,
    operation: str,
    mode: str,
    requested_by: str,
    request_id: str,
    attempts: int = 0,
) -> str:
    message_id = await redis.xadd(
        JOB_STREAM,
        {
            "job_id": job_id,
            "document_id": document_id,
            "tenant_id": tenant_id,
            "operation": operation,
            "mode": mode,
            "requested_by": requested_by,
            "request_id": request_id,
            "attempts": str(attempts),
        },
    )
    return message_id.decode() if isinstance(message_id, bytes) else str(message_id)


def decode_job(fields: dict[Any, Any]) -> dict[str, str]:
    decoded: dict[str, str] = {}
    for key, value in fields.items():
        clean_key = key.decode() if isinstance(key, bytes) else str(key)
        clean_value = value.decode() if isinstance(value, bytes) else str(value)
        decoded[clean_key] = clean_value
    required = {
        "job_id",
        "document_id",
        "tenant_id",
        "operation",
        "mode",
        "requested_by",
        "request_id",
        "attempts",
    }
    missing = required.difference(decoded)
    if missing:
        raise ValueError("任务消息缺少字段: " + ", ".join(sorted(missing)))
    empty = [field for field in required if not decoded[field].strip()]
    if empty:
        raise ValueError("任务消息字段不能为空: " + ", ".join(sorted(empty)))
    return decoded
