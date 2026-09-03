from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    inspect,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config import settings


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


class Base(DeclarativeBase):
    pass


class KnowledgeDocumentRecord(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (UniqueConstraint("tenant_id", "id", name="uq_document_tenant_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_name: Mapped[str] = mapped_column(String(512))
    title: Mapped[str] = mapped_column(String(512))
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    acl: Mapped[list[str]] = mapped_column(JSON, default=list)
    upload_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    mode: Mapped[str] = mapped_column(String(32), default="rag")
    file_path: Mapped[str] = mapped_column(Text)
    file_path_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingest_progress: Mapped[int] = mapped_column(Integer, default=0)
    ingest_total: Mapped[int] = mapped_column(Integer, default=0)
    ingest_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    backend_status: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class IngestionJobRecord(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    operation: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(32), default="milvus")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class UploadSessionRecord(Base):
    __tablename__ = "upload_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_name: Mapped[str] = mapped_column(String(512))
    file_size: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(512), default="")
    mode: Mapped[str] = mapped_column(String(32), default="rag")
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    acl: Mapped[list[str]] = mapped_column(JSON, default=list)
    chunk_size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditEventRecord(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("source IN ('api', 'worker')", name="ck_audit_events_source"),
        CheckConstraint("outcome IN ('success', 'failure', 'denied')", name="ck_audit_events_outcome"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_type: Mapped[str] = mapped_column(String(32), default="user")
    source: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    details: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class ConversationRecord(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "owner_id", "thread_id", name="uq_conversation_scope_thread"),
        CheckConstraint(
            "status IN ('running', 'waiting', 'completed', 'failed', 'cancelled')",
            name="ck_conversations_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    waiting_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ConversationMessageRecord(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'status', 'error')",
            name="ck_conversation_messages_role",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    references: Mapped[list[str]] = mapped_column(JSON, default=list)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class ConversationFeedbackRecord(Base):
    __tablename__ = "conversation_feedback"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_conversation_feedback_message_user"),
        CheckConstraint("rating IN ('helpful', 'not_helpful')", name="ck_conversation_feedback_rating"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conversation_messages.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    rating: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


_engine: AsyncEngine = create_async_engine(settings.database.url, echo=settings.database.echo, pool_pre_ping=True)
SessionFactory = async_sessionmaker(_engine, expire_on_commit=False)


async def reconfigure_database(url: str) -> None:
    """测试或独立 Worker 启动时显式切换数据库连接。"""
    global _engine
    await _engine.dispose()
    _engine = create_async_engine(url, echo=False, pool_pre_ping=True)
    SessionFactory.configure(bind=_engine)


async def init_database() -> None:
    async with _engine.begin() as connection:
        if settings.runtime.environment != "production":
            await connection.run_sync(Base.metadata.create_all)

        def schema_issues(sync_connection: Any) -> list[str]:
            inspector = inspect(sync_connection)
            actual_tables = set(inspector.get_table_names())
            issues: list[str] = []
            for table_name, table in Base.metadata.tables.items():
                if table_name not in actual_tables:
                    issues.append(f"缺少表 {table_name}")
                    continue
                actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
                missing_columns = set(table.columns.keys()).difference(actual_columns)
                if missing_columns:
                    issues.append(f"表 {table_name} 缺少列 {','.join(sorted(missing_columns))}")
            return issues

        issues = await connection.run_sync(schema_issues)
        if issues:
            raise RuntimeError("数据库迁移未完成: " + "; ".join(issues) + "。请执行 python -m alembic upgrade head")


async def close_database() -> None:
    await _engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session


def document_to_dict(record: KnowledgeDocumentRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "file_name": record.file_name,
        "title": record.title,
        "tenant_id": record.tenant_id,
        "owner_id": record.owner_id,
        "acl": record.acl,
        "upload_time": record.upload_time.isoformat(),
        "mode": record.mode,
        "file_path": record.file_path,
        "file_path_md": record.file_path_md,
        "status": record.status,
        "chunk_count": record.chunk_count,
        "error": record.error,
        "ingest_progress": record.ingest_progress,
        "ingest_total": record.ingest_total,
        "ingest_message": record.ingest_message,
        "batch_id": record.batch_id,
        "version": record.version,
        "checksum": record.checksum,
        "backend_status": record.backend_status,
    }


async def create_document(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    record = KnowledgeDocumentRecord(**payload)
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return document_to_dict(record)


async def list_documents(session: AsyncSession, tenant_id: str) -> list[dict[str, Any]]:
    result = await session.scalars(
        select(KnowledgeDocumentRecord)
        .where(KnowledgeDocumentRecord.tenant_id == tenant_id)
        .order_by(KnowledgeDocumentRecord.upload_time.desc())
    )
    return [document_to_dict(record) for record in result.all()]


async def get_document(
    session: AsyncSession,
    document_id: str,
    tenant_id: str,
) -> dict[str, Any] | None:
    record = await session.scalar(
        select(KnowledgeDocumentRecord).where(
            KnowledgeDocumentRecord.id == document_id,
            KnowledgeDocumentRecord.tenant_id == tenant_id,
        )
    )
    return document_to_dict(record) if record else None


async def update_document(
    session: AsyncSession,
    document_id: str,
    tenant_id: str,
    **updates: Any,
) -> dict[str, Any] | None:
    record = await session.scalar(
        select(KnowledgeDocumentRecord).where(
            KnowledgeDocumentRecord.id == document_id,
            KnowledgeDocumentRecord.tenant_id == tenant_id,
        )
    )
    if record is None:
        return None
    for key, value in updates.items():
        if not hasattr(record, key):
            raise ValueError(f"不支持更新字段: {key}")
        setattr(record, key, value)
    record.updated_at = utc_now()
    await session.commit()
    await session.refresh(record)
    return document_to_dict(record)


async def remove_document_record(session: AsyncSession, document_id: str, tenant_id: str) -> bool:
    record = await session.scalar(
        select(KnowledgeDocumentRecord).where(
            KnowledgeDocumentRecord.id == document_id,
            KnowledgeDocumentRecord.tenant_id == tenant_id,
        )
    )
    if record is None:
        return False
    await session.delete(record)
    await session.commit()
    return True


async def create_job(
    session: AsyncSession,
    *,
    job_id: str,
    document_id: str,
    tenant_id: str,
    operation: str,
    mode: str,
    requested_by: str,
    request_id: str | None,
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
    await session.commit()
    await session.refresh(record)
    return record


async def update_job(session: AsyncSession, job_id: str, **updates: Any) -> IngestionJobRecord | None:
    record = await session.get(IngestionJobRecord, job_id)
    if record is None:
        return None
    for key, value in updates.items():
        if not hasattr(record, key):
            raise ValueError(f"不支持更新任务字段: {key}")
        setattr(record, key, value)
    record.updated_at = utc_now()
    await session.commit()
    await session.refresh(record)
    return record


async def create_upload_session(session: AsyncSession, payload: dict[str, Any]) -> UploadSessionRecord:
    record = UploadSessionRecord(**payload)
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def get_upload_session(
    session: AsyncSession,
    upload_id: str,
    tenant_id: str,
    owner_id: str,
) -> UploadSessionRecord | None:
    return await session.scalar(
        select(UploadSessionRecord).where(
            UploadSessionRecord.id == upload_id,
            UploadSessionRecord.tenant_id == tenant_id,
            UploadSessionRecord.owner_id == owner_id,
        )
    )


async def remove_upload_session(session: AsyncSession, upload_id: str) -> None:
    record = await session.get(UploadSessionRecord, upload_id)
    if record is not None:
        await session.delete(record)
        await session.commit()


def conversation_to_dict(record: ConversationRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "thread_id": record.thread_id,
        "tenant_id": record.tenant_id,
        "owner_id": record.owner_id,
        "title": record.title,
        "status": record.status,
        "waiting_prompt": record.waiting_prompt,
        "attachment_count": record.attachment_count,
        "created_at": utc_iso(record.created_at),
        "updated_at": utc_iso(record.updated_at),
    }


def conversation_message_to_dict(record: ConversationMessageRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "role": record.role,
        "content": record.content,
        "references": record.references,
        "attachments": record.attachments,
        "created_at": utc_iso(record.created_at),
    }


async def ensure_conversation(
    session: AsyncSession,
    *,
    thread_id: str,
    tenant_id: str,
    owner_id: str,
    title: str,
    attachment_count: int,
) -> dict[str, Any]:
    record = await session.scalar(
        select(ConversationRecord).where(
            ConversationRecord.thread_id == thread_id,
            ConversationRecord.tenant_id == tenant_id,
            ConversationRecord.owner_id == owner_id,
        )
    )
    if record is None:
        record = ConversationRecord(
            id=uuid.uuid4().hex,
            thread_id=thread_id,
            tenant_id=tenant_id,
            owner_id=owner_id,
            title=title,
            attachment_count=attachment_count,
        )
        session.add(record)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            record = await session.scalar(
                select(ConversationRecord).where(
                    ConversationRecord.thread_id == thread_id,
                    ConversationRecord.tenant_id == tenant_id,
                    ConversationRecord.owner_id == owner_id,
                )
            )
            if record is None:
                raise
            record.status = "running"
            record.waiting_prompt = None
            record.attachment_count += attachment_count
            record.updated_at = utc_now()
            await session.commit()
    else:
        record.status = "running"
        record.waiting_prompt = None
        record.attachment_count += attachment_count
        record.updated_at = utc_now()
        await session.commit()
    await session.refresh(record)
    return conversation_to_dict(record)


async def append_conversation_message(
    session: AsyncSession,
    *,
    conversation_id: str,
    role: str,
    content: str,
    references: list[str] | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    record = ConversationMessageRecord(
        id=uuid.uuid4().hex,
        conversation_id=conversation_id,
        role=role,
        content=content,
        references=references or [],
        attachments=attachments or [],
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return conversation_message_to_dict(record)


async def finish_conversation_turn(
    session: AsyncSession,
    *,
    conversation_id: str,
    status: str,
    role: str | None = None,
    content: str | None = None,
    references: list[str] | None = None,
) -> None:
    record = await session.get(ConversationRecord, conversation_id)
    if record is None:
        raise RuntimeError("会话记录不存在")
    record.status = status
    record.waiting_prompt = content if status == "waiting" else None
    record.updated_at = utc_now()
    if role and content:
        session.add(
            ConversationMessageRecord(
                id=uuid.uuid4().hex,
                conversation_id=conversation_id,
                role=role,
                content=content,
                references=references or [],
                attachments=[],
            )
        )
    await session.commit()


async def list_user_conversations(
    session: AsyncSession,
    *,
    tenant_id: str,
    owner_id: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    result = await session.scalars(
        select(ConversationRecord)
        .where(ConversationRecord.tenant_id == tenant_id, ConversationRecord.owner_id == owner_id)
        .order_by(ConversationRecord.updated_at.desc())
        .limit(limit)
    )
    return [conversation_to_dict(record) for record in result.all()]


async def list_tenant_conversation_feedback(
    session: AsyncSession,
    *,
    tenant_id: str,
    limit: int = 200,
) -> tuple[list[dict[str, Any]], bool]:
    if not 1 <= limit <= 200:
        raise ValueError("反馈查询数量必须在 1 到 200 之间")
    result = await session.execute(
        select(ConversationFeedbackRecord, ConversationRecord)
        .join(ConversationRecord, ConversationRecord.id == ConversationFeedbackRecord.conversation_id)
        .where(ConversationRecord.tenant_id == tenant_id)
        .order_by(ConversationFeedbackRecord.updated_at.desc(), ConversationFeedbackRecord.id.desc())
        .limit(limit + 1)
    )
    rows = result.all()
    window_complete = len(rows) <= limit
    return [
        {
            "id": feedback.id,
            "conversation_id": conversation.id,
            "thread_id": conversation.thread_id,
            "respondent_id": feedback.user_id,
            "conversation_status": conversation.status,
            "rating": feedback.rating,
            "created_at": utc_iso(feedback.created_at),
            "updated_at": utc_iso(feedback.updated_at),
            "conversation_updated_at": utc_iso(conversation.updated_at),
        }
        for feedback, conversation in rows[:limit]
    ], window_complete


async def get_user_conversation(
    session: AsyncSession,
    *,
    thread_id: str,
    tenant_id: str,
    owner_id: str,
) -> dict[str, Any] | None:
    record = await session.scalar(
        select(ConversationRecord).where(
            ConversationRecord.thread_id == thread_id,
            ConversationRecord.tenant_id == tenant_id,
            ConversationRecord.owner_id == owner_id,
        )
    )
    if record is None:
        return None
    messages = await session.scalars(
        select(ConversationMessageRecord)
        .where(ConversationMessageRecord.conversation_id == record.id)
        .order_by(ConversationMessageRecord.created_at.asc(), ConversationMessageRecord.id.asc())
    )
    payload = conversation_to_dict(record)
    payload["messages"] = [conversation_message_to_dict(message) for message in messages.all()]
    latest_assistant_id = await session.scalar(
        select(ConversationMessageRecord.id)
        .where(
            ConversationMessageRecord.conversation_id == record.id,
            ConversationMessageRecord.role == "assistant",
        )
        .order_by(ConversationMessageRecord.created_at.desc(), ConversationMessageRecord.id.desc())
        .limit(1)
    )
    feedback = None
    if latest_assistant_id:
        feedback = await session.scalar(
            select(ConversationFeedbackRecord).where(
                ConversationFeedbackRecord.message_id == latest_assistant_id,
                ConversationFeedbackRecord.user_id == owner_id,
            )
        )
    payload["feedback"] = feedback.rating if feedback else None
    return payload


async def set_conversation_feedback(
    session: AsyncSession,
    *,
    conversation_id: str,
    user_id: str,
    rating: str,
) -> bool:
    message_id = await session.scalar(
        select(ConversationMessageRecord.id)
        .where(
            ConversationMessageRecord.conversation_id == conversation_id,
            ConversationMessageRecord.role == "assistant",
        )
        .order_by(ConversationMessageRecord.created_at.desc(), ConversationMessageRecord.id.desc())
        .limit(1)
    )
    if message_id is None:
        return False
    record = await session.scalar(
        select(ConversationFeedbackRecord).where(
            ConversationFeedbackRecord.message_id == message_id,
            ConversationFeedbackRecord.user_id == user_id,
        )
    )
    if record is None:
        session.add(
            ConversationFeedbackRecord(
                id=uuid.uuid4().hex,
                conversation_id=conversation_id,
                message_id=message_id,
                user_id=user_id,
                rating=rating,
            )
        )
    else:
        record.rating = rating
        record.updated_at = utc_now()
    await session.commit()
    return True
