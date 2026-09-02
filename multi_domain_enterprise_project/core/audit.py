from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from multi_domain_enterprise_project.core.database import (
    AuditEventRecord,
    IngestionJobRecord,
    KnowledgeDocumentRecord,
    UploadSessionRecord,
    document_to_dict,
    utc_now,
)

AuditOutcome = Literal["success", "failure", "denied"]
AuditSource = Literal["api", "worker"]

_SENSITIVE_KEY_PARTS = {
    "authorization",
    "content",
    "cookie",
    "file_name",
    "filename",
    "password",
    "path",
    "prompt",
    "query",
    "secret",
    "token",
}
_MAX_METADATA_BYTES = 4096


def _validate_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    def validate_keys(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = str(key).lower().replace("-", "_")
                if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
                    raise ValueError(f"审计元数据禁止敏感字段: {key}")
                validate_keys(nested)
        elif isinstance(value, list):
            for nested in value:
                validate_keys(nested)

    validate_keys(metadata)
    try:
        encoded = json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("审计元数据必须可序列化为 JSON") from exc
    if len(encoded) > _MAX_METADATA_BYTES:
        raise ValueError("审计元数据超过 4096 字节")
    return metadata


def audit_event_to_dict(record: AuditEventRecord) -> dict[str, Any]:
    occurred_at = record.occurred_at
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    return {
        "id": record.id,
        "tenant_id": record.tenant_id,
        "actor_id": record.actor_id,
        "actor_type": record.actor_type,
        "source": record.source,
        "action": record.action,
        "resource_type": record.resource_type,
        "resource_id": record.resource_id,
        "outcome": record.outcome,
        "request_id": record.request_id,
        "metadata": record.details,
        "occurred_at": occurred_at.isoformat(),
    }


async def append_audit_event(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str,
    source: AuditSource,
    action: str,
    resource_type: str,
    outcome: AuditOutcome,
    resource_id: str | None = None,
    request_id: str | None = None,
    actor_type: str = "user",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = build_audit_event(
        tenant_id=tenant_id,
        actor_id=actor_id,
        source=source,
        action=action,
        resource_type=resource_type,
        outcome=outcome,
        resource_id=resource_id,
        request_id=request_id,
        actor_type=actor_type,
        metadata=metadata,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return audit_event_to_dict(record)


def build_audit_event(
    *,
    tenant_id: str,
    actor_id: str,
    source: AuditSource,
    action: str,
    resource_type: str,
    outcome: AuditOutcome,
    resource_id: str | None = None,
    request_id: str | None = None,
    actor_type: str = "user",
    metadata: dict[str, Any] | None = None,
) -> AuditEventRecord:
    required = {
        "tenant_id": tenant_id,
        "actor_id": actor_id,
        "source": source,
        "action": action,
        "resource_type": resource_type,
        "outcome": outcome,
    }
    empty = [name for name, value in required.items() if not str(value).strip()]
    if empty:
        raise ValueError("审计事件缺少字段: " + ", ".join(empty))
    return AuditEventRecord(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_type=actor_type,
        source=source,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        request_id=request_id,
        details=_validate_metadata(metadata or {}),
        occurred_at=utc_now(),
    )


async def create_document_with_audit(
    session: AsyncSession,
    payload: dict[str, Any],
    *,
    actor_id: str,
    request_id: str,
    metadata: dict[str, Any],
    upload_session: UploadSessionRecord | None = None,
) -> dict[str, Any]:
    record = KnowledgeDocumentRecord(**payload)
    session.add(record)
    if upload_session is not None:
        await session.delete(upload_session)
    session.add(
        build_audit_event(
            tenant_id=payload["tenant_id"],
            actor_id=actor_id,
            source="api",
            action="document.uploaded",
            resource_type="document",
            resource_id=payload["id"],
            outcome="success",
            request_id=request_id,
            metadata=metadata,
        )
    )
    await session.commit()
    await session.refresh(record)
    return document_to_dict(record)


async def create_upload_session_with_audit(
    session: AsyncSession,
    payload: dict[str, Any],
    *,
    actor_id: str,
    request_id: str,
) -> UploadSessionRecord:
    record = UploadSessionRecord(**payload)
    session.add(record)
    session.add(
        build_audit_event(
            tenant_id=payload["tenant_id"],
            actor_id=actor_id,
            source="api",
            action="upload_session.created",
            resource_type="upload_session",
            resource_id=payload["id"],
            outcome="success",
            request_id=request_id,
            metadata={"file_size": payload["file_size"], "mode": payload["mode"]},
        )
    )
    await session.commit()
    await session.refresh(record)
    return record


async def create_job_with_audit(
    session: AsyncSession,
    *,
    job_id: str,
    document_id: str,
    tenant_id: str,
    operation: str,
    mode: str,
    requested_by: str,
    request_id: str,
) -> IngestionJobRecord:
    record = IngestionJobRecord(
        id=job_id,
        document_id=document_id,
        tenant_id=tenant_id,
        operation=operation,
        mode=mode,
        requested_by=requested_by,
        request_id=request_id,
    )
    session.add(record)
    session.add(
        build_audit_event(
            tenant_id=tenant_id,
            actor_id=requested_by,
            source="api",
            action=f"document.{operation}_requested",
            resource_type="document",
            resource_id=document_id,
            outcome="success",
            request_id=request_id,
            metadata={"job_id": job_id, "mode": mode},
        )
    )
    await session.commit()
    await session.refresh(record)
    return record


def _encode_cursor(record: AuditEventRecord) -> str:
    occurred_at = record.occurred_at
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    payload = json.dumps([occurred_at.isoformat(), record.id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        occurred_text, event_id = json.loads(base64.urlsafe_b64decode(cursor + padding))
        occurred_at = datetime.fromisoformat(occurred_text)
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        if not event_id:
            raise ValueError
        return occurred_at, str(event_id)
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error) as exc:
        raise ValueError("审计事件游标无效") from exc


async def list_audit_events(
    session: AsyncSession,
    *,
    tenant_id: str,
    limit: int,
    cursor: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    actor_id: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    if not 1 <= limit <= 200:
        raise ValueError("审计事件查询数量必须在 1 到 200 之间")
    statement = select(AuditEventRecord).where(AuditEventRecord.tenant_id == tenant_id)
    if action:
        statement = statement.where(AuditEventRecord.action == action)
    if outcome:
        statement = statement.where(AuditEventRecord.outcome == outcome)
    if actor_id:
        statement = statement.where(AuditEventRecord.actor_id == actor_id)
    if cursor:
        occurred_at, event_id = _decode_cursor(cursor)
        statement = statement.where(
            or_(
                AuditEventRecord.occurred_at < occurred_at,
                and_(AuditEventRecord.occurred_at == occurred_at, AuditEventRecord.id < event_id),
            )
        )
    result = await session.scalars(
        statement.order_by(AuditEventRecord.occurred_at.desc(), AuditEventRecord.id.desc()).limit(limit + 1)
    )
    records = list(result.all())
    has_more = len(records) > limit
    page = records[:limit]
    next_cursor = _encode_cursor(page[-1]) if has_more and page else None
    return [audit_event_to_dict(record) for record in page], next_cursor


async def get_audit_event(
    session: AsyncSession,
    *,
    tenant_id: str,
    event_id: str,
) -> dict[str, Any] | None:
    record = await session.scalar(
        select(AuditEventRecord).where(
            AuditEventRecord.id == event_id,
            AuditEventRecord.tenant_id == tenant_id,
        )
    )
    return audit_event_to_dict(record) if record else None


async def list_request_audit_events(
    session: AsyncSession,
    *,
    tenant_id: str,
    request_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if not request_id.strip():
        return []
    if not 1 <= limit <= 200:
        raise ValueError("审计追踪查询数量必须在 1 到 200 之间")
    result = await session.scalars(
        select(AuditEventRecord)
        .where(
            AuditEventRecord.tenant_id == tenant_id,
            AuditEventRecord.request_id == request_id,
        )
        .order_by(AuditEventRecord.occurred_at.asc(), AuditEventRecord.id.asc())
        .limit(limit)
    )
    return [audit_event_to_dict(record) for record in result.all()]
