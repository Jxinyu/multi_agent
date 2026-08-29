from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.redis import AsyncRedisSaver
from prometheus_client import make_asgi_app
from pydantic import BaseModel, Field, field_validator, model_validator
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings, validate_runtime_settings
from multi_domain_enterprise_project.agent.agent_main import run_agent_stream
from multi_domain_enterprise_project.api.enterprise import router as enterprise_router
from multi_domain_enterprise_project.core.audit import (
    append_audit_event,
    create_document_with_audit,
    create_job_with_audit,
    create_upload_session_with_audit,
    list_audit_events,
)
from multi_domain_enterprise_project.core.auth import (
    AuthTokenResponse,
    CurrentUser,
    create_development_token,
    get_current_user,
    require_permissions,
)
from multi_domain_enterprise_project.core.database import (
    IngestionJobRecord,
    SessionFactory,
    close_database,
    get_document,
    get_session,
    get_upload_session,
    init_database,
    list_documents,
    update_document,
    update_job,
    utc_now,
)
from multi_domain_enterprise_project.core.jobs import enqueue_job, ensure_job_group
from multi_domain_enterprise_project.core.observability import (
    RequestContextMiddleware,
    configure_logging,
    configure_tracing,
    request_id_var,
)
from multi_domain_enterprise_project.core.search import parse_retrieval_context
from multi_domain_enterprise_project.core.storage import (
    combine_chunks,
    decode_attachment,
    document_path,
    ensure_storage_roots,
    normalized_extension,
    remove_upload_session_files,
    stream_upload,
    upload_session_dir,
    validate_file_signature,
)
from multi_domain_enterprise_project.core.user_views import (
    SearchEvidenceItem,
    SearchRequest,
    SearchResponse,
    UserTaskListResponse,
    build_user_tasks,
)
from multi_domain_enterprise_project.healthcheck import run_checks
from multi_domain_enterprise_project.rag.authorization import RetrievalAuthorization, is_metadata_authorized
from multi_domain_enterprise_project.rag.documentParser.parser_route import DocumentParserRouter
from multi_domain_enterprise_project.rag.rag_service import retrieve_service

configure_logging()
configure_tracing()
logger = logging.getLogger(__name__)
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,modelscope.net,bigmodel.cn,xiaoai.plus")

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
FRONTEND_INDEX = FRONTEND_DIST / "index.html"
RESUMABLE_CHUNK_SIZE = 2 * 1024 * 1024

redis_conn: Redis | None = None
global_checkpointer: Any = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_conn, global_checkpointer
    validate_runtime_settings(settings)
    ensure_storage_roots()
    await init_database()

    redis_conn = Redis.from_url(settings.llm_key.redis, decode_responses=False)
    await redis_conn.ping()
    await ensure_job_group(redis_conn)
    app.state.redis = redis_conn

    async with AsyncRedisSaver.from_conn_string(settings.llm_key.redis) as checkpointer:
        await checkpointer.asetup()
        global_checkpointer = checkpointer
        logger.info("应用依赖初始化完成")
        yield

    global_checkpointer = None
    await redis_conn.aclose()
    redis_conn = None
    await close_database()
    logger.info("应用资源已释放")


app = FastAPI(title="企业多智能体助手", version="1.0.0", lifespan=lifespan)
app.include_router(enterprise_router)
app.add_middleware(RequestContextMiddleware)
if settings.runtime.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.runtime.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
app.mount("/metrics", make_asgi_app(), name="metrics")


class AttachmentPayload(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(max_length=128)
    data_base64: str = Field(min_length=1)


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    thread_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,128}$")
    attachments: list[AttachmentPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_attachment_count(self) -> ChatRequest:
        if len(self.attachments) > settings.upload.max_attachments_per_request:
            raise ValueError("附件数量超过限制")
        return self


class CurrentUserResponse(BaseModel):
    user: CurrentUser


class KnowledgeBaseItem(BaseModel):
    id: str
    file_name: str
    title: str
    tenant_id: str
    owner_id: str
    acl: list[str]
    upload_time: str
    mode: str
    status: str = "uploaded"
    chunk_count: int = 0
    error: str | None = None
    ingest_progress: int = 0
    ingest_total: int = 0
    ingest_message: str | None = None
    batch_id: str | None = None
    version: int = 1
    checksum: str
    backend_status: dict[str, str] = Field(default_factory=dict)


class KnowledgeBaseListResponse(BaseModel):
    items: list[KnowledgeBaseItem]


class UploadResponse(BaseModel):
    item: KnowledgeBaseItem | None = None
    items: list[KnowledgeBaseItem] | None = None


class IngestRequest(BaseModel):
    mode: Literal["rag", "graphrag", "hybrid"] = "rag"


class BulkIngestRequest(IngestRequest):
    ids: list[str] = Field(min_length=1, max_length=100)


class BulkDeleteRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)


class ResumableUploadInitRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    file_size: int = Field(gt=0)
    title: str = Field(default="", max_length=512)
    mode: Literal["rag", "graphrag", "hybrid"] = "rag"

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: str) -> str:
        normalized_extension(value)
        return Path(value).name


class ResumableUploadInitResponse(BaseModel):
    upload_id: str
    uploaded_chunks: list[int] = Field(default_factory=list)
    chunk_size: int


class ResumableUploadStatusResponse(BaseModel):
    upload_id: str
    uploaded_chunks: list[int]
    chunk_size: int
    file_size: int


class ResumableUploadCompleteRequest(BaseModel):
    upload_id: str = Field(pattern=r"^[A-Za-z0-9_-]{16,64}$")


class DeleteResponse(BaseModel):
    success: bool


class JobResponse(BaseModel):
    id: str
    document_id: str
    operation: str
    mode: str
    status: str
    attempts: int
    error: str | None


class AuditEventItem(BaseModel):
    id: str
    tenant_id: str
    actor_id: str
    actor_type: str
    source: str
    action: str
    resource_type: str
    resource_id: str | None
    outcome: str
    request_id: str | None
    metadata: dict[str, Any]
    occurred_at: str


class AuditEventListResponse(BaseModel):
    items: list[AuditEventItem]
    next_cursor: str | None = None


Session = Annotated[AsyncSession, Depends(get_session)]
Authenticated = Annotated[CurrentUser, Depends(get_current_user)]
ChatUser = Annotated[CurrentUser, Depends(require_permissions("chat:use"))]
KbReader = Annotated[CurrentUser, Depends(require_permissions("kb:read"))]
KbWriter = Annotated[CurrentUser, Depends(require_permissions("kb:write"))]
KbDeleter = Annotated[CurrentUser, Depends(require_permissions("kb:delete"))]
AuditReader = Annotated[CurrentUser, Depends(require_permissions("audit:read"))]


def _item(payload: dict[str, Any]) -> KnowledgeBaseItem:
    return KnowledgeBaseItem(**payload)


async def _require_document(session: AsyncSession, document_id: str, user: CurrentUser) -> dict[str, Any]:
    item = await get_document(session, document_id, user.tenant_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return item


async def _rate_limit(user: CurrentUser, action: str) -> None:
    if redis_conn is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="限流服务未初始化")
    minute = int(time.time() // 60)
    key = f"rate:{user.tenant_id}:{user.user_id}:{action}:{minute}"
    count = await redis_conn.incr(key)
    if count == 1:
        await redis_conn.expire(key, 120)
    if count > settings.runtime.request_rate_limit_per_minute:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="请求过于频繁")


def _uploaded_chunk_indexes(upload_id: str) -> list[int]:
    chunks_dir = upload_session_dir(upload_id) / "chunks"
    if not chunks_dir.exists():
        return []
    indexes: list[int] = []
    for path in chunks_dir.glob("*.part"):
        try:
            indexes.append(int(path.stem))
        except ValueError:
            continue
    return sorted(indexes)


async def _build_attachment_context(attachments: list[AttachmentPayload]) -> tuple[str, list[str]]:
    if not attachments:
        return "", []
    router = DocumentParserRouter(mode="auto")
    sections: list[str] = []
    names: list[str] = []
    with tempfile.TemporaryDirectory(prefix="rag-upper-attachments-") as temp_dir:
        root = Path(temp_dir)
        for attachment in attachments:
            extension = normalized_extension(attachment.name)
            data = decode_attachment(attachment.data_base64, settings.upload.max_attachment_size_bytes)
            path = root / f"{uuid.uuid4().hex}{extension}"
            path.write_bytes(data)
            validate_file_signature(path, extension)
            parsed = await router.route_and_parse(str(path))
            sections.append(f"### 附件: {Path(attachment.name).name}\n{parsed}")
            names.append(Path(attachment.name).name)
    return "\n\n".join(sections), names


async def _queue_document_job(
    session: AsyncSession,
    item: dict[str, Any],
    *,
    operation: str,
    mode: str,
    current_user: CurrentUser,
) -> None:
    if redis_conn is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="任务队列未初始化")
    job_id = uuid.uuid4().hex
    request_id = request_id_var.get()
    await create_job_with_audit(
        session,
        job_id=job_id,
        document_id=item["id"],
        tenant_id=item["tenant_id"],
        operation=operation,
        mode=mode,
        requested_by=current_user.user_id,
        request_id=request_id,
    )
    try:
        await enqueue_job(
            redis_conn,
            job_id=job_id,
            document_id=item["id"],
            tenant_id=item["tenant_id"],
            operation=operation,
            mode=mode,
            requested_by=current_user.user_id,
            request_id=request_id,
        )
    except Exception as exc:
        await update_job(session, job_id, status="failed", error="任务入队失败")
        await update_document(
            session,
            item["id"],
            item["tenant_id"],
            status="delete_failed" if operation == "delete" else "failed",
            error="任务入队失败",
            ingest_message="任务未进入队列",
        )
        await append_audit_event(
            session,
            tenant_id=current_user.tenant_id,
            actor_id=current_user.user_id,
            source="api",
            action=f"document.{operation}_enqueue",
            resource_type="document",
            resource_id=item["id"],
            outcome="failure",
            request_id=request_id,
            metadata={"job_id": job_id, "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="任务入队失败") from exc


@app.post("/api/auth/development-token", response_model=AuthTokenResponse)
async def development_token() -> AuthTokenResponse:
    return create_development_token()


@app.get("/api/auth/me", response_model=CurrentUserResponse)
async def get_me(current_user: Authenticated) -> CurrentUserResponse:
    return CurrentUserResponse(user=current_user)


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest, current_user: ChatUser, session: Session):
    await _rate_limit(current_user, "chat")
    chat_request_id = request_id_var.get()
    await append_audit_event(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        source="api",
        action="chat.requested",
        resource_type="conversation",
        resource_id=request.thread_id,
        outcome="success",
        request_id=chat_request_id,
        metadata={"attachment_count": len(request.attachments)},
    )
    internal_thread_id = f"{current_user.tenant_id}:{current_user.user_id}:{request.thread_id}"
    config: dict[str, Any] = {
        "configurable": {
            "thread_id": internal_thread_id,
            "access_token": current_user.access_token,
            "user_info": {
                "user_id": current_user.user_id,
                "tenant_id": current_user.tenant_id,
                "role": current_user.role,
                "groups": current_user.groups,
            },
        }
    }

    async def event_generator():
        if global_checkpointer is None:
            async with SessionFactory() as audit_session:
                await append_audit_event(
                    audit_session,
                    tenant_id=current_user.tenant_id,
                    actor_id=current_user.user_id,
                    source="api",
                    action="chat.failed",
                    resource_type="conversation",
                    resource_id=request.thread_id,
                    outcome="failure",
                    request_id=chat_request_id,
                    metadata={"error_type": "CheckpointerUnavailable"},
                )
            yield f"data: {json.dumps({'type': 'error', 'message': '会话服务未就绪'}, ensure_ascii=False)}\n\n"
            return
        try:
            attachment_context, names = await _build_attachment_context(request.attachments)
            if names:
                yield f"data: {json.dumps({'type': 'status', 'message': f'已解析 {len(names)} 个附件'}, ensure_ascii=False)}\n\n"
            query = request.query
            if attachment_context:
                query = f"{query}\n\n【附件解析内容】\n{attachment_context}\n\n请结合附件内容回答。"
            terminal_chunk: dict[str, Any] | None = None
            async for chunk in run_agent_stream(query=query, config=config, checkpointer=global_checkpointer):
                if chunk.get("type") in {"complete", "interrupt", "error"}:
                    terminal_chunk = chunk
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            async with SessionFactory() as audit_session:
                terminal_type = (terminal_chunk or {}).get("type")
                if terminal_type == "complete":
                    action, outcome = "chat.completed", "success"
                elif terminal_type == "interrupt":
                    action, outcome = "chat.waiting_input", "success"
                else:
                    action, outcome = "chat.failed", "failure"
                await append_audit_event(
                    audit_session,
                    tenant_id=current_user.tenant_id,
                    actor_id=current_user.user_id,
                    source="api",
                    action=action,
                    resource_type="conversation",
                    resource_id=request.thread_id,
                    outcome=outcome,
                    request_id=chat_request_id,
                    metadata={"attachment_count": len(request.attachments)},
                )
        except asyncio.CancelledError:
            async with SessionFactory() as audit_session:
                await append_audit_event(
                    audit_session,
                    tenant_id=current_user.tenant_id,
                    actor_id=current_user.user_id,
                    source="api",
                    action="chat.cancelled",
                    resource_type="conversation",
                    resource_id=request.thread_id,
                    outcome="failure",
                    request_id=chat_request_id,
                    metadata={"attachment_count": len(request.attachments)},
                )
            raise
        except HTTPException as exc:
            async with SessionFactory() as audit_session:
                await append_audit_event(
                    audit_session,
                    tenant_id=current_user.tenant_id,
                    actor_id=current_user.user_id,
                    source="api",
                    action="chat.failed",
                    resource_type="conversation",
                    resource_id=request.thread_id,
                    outcome="failure",
                    request_id=chat_request_id,
                    metadata={"error_type": type(exc).__name__, "status_code": exc.status_code},
                )
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc.detail)}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("聊天流处理失败")
            async with SessionFactory() as audit_session:
                await append_audit_event(
                    audit_session,
                    tenant_id=current_user.tenant_id,
                    actor_id=current_user.user_id,
                    source="api",
                    action="chat.failed",
                    resource_type="conversation",
                    resource_id=request.thread_id,
                    outcome="failure",
                    request_id=chat_request_id,
                    metadata={"error_type": type(exc).__name__},
                )
            yield f"data: {json.dumps({'type': 'error', 'message': '请求处理失败，请稍后重试'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/search", response_model=SearchResponse)
async def api_search(request: SearchRequest, current_user: KbReader, session: Session):
    await _rate_limit(current_user, "search")
    started = time.perf_counter()
    context = await retrieve_service(
        query_str=request.query,
        title=request.title,
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        acl_list=current_user.groups,
        mode=request.mode,
    )
    items = parse_retrieval_context(context)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    await append_audit_event(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        source="api",
        action="search.completed",
        resource_type="knowledge_index",
        outcome="success",
        request_id=request_id_var.get(),
        metadata={
            "input_digest": hashlib.sha256(request.query.encode()).hexdigest(),
            "mode": request.mode,
            "result_count": len(items),
            "elapsed_ms": elapsed_ms,
        },
    )
    return SearchResponse(items=[SearchEvidenceItem(**item) for item in items], mode=request.mode, elapsed_ms=elapsed_ms)


@app.get("/api/tasks", response_model=UserTaskListResponse)
async def api_list_user_tasks(current_user: ChatUser, session: Session):
    events, _ = await list_audit_events(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        limit=200,
    )
    return UserTaskListResponse(items=build_user_tasks(events))


@app.get("/api/documents", response_model=KnowledgeBaseListResponse)
async def api_list_user_documents(current_user: KbReader, session: Session):
    items = await list_documents(session, current_user.tenant_id)
    scope = RetrievalAuthorization(
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        acl=tuple(current_user.groups),
    )
    authorized = [item for item in items if is_metadata_authorized(item, scope)]
    return KnowledgeBaseListResponse(items=[_item(item) for item in authorized])


@app.get("/api/admin/documents", response_model=KnowledgeBaseListResponse)
async def api_list_documents(current_user: KbReader, session: Session):
    items = await list_documents(session, current_user.tenant_id)
    await append_audit_event(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        source="api",
        action="document.listed",
        resource_type="document_collection",
        outcome="success",
        request_id=request_id_var.get(),
        metadata={"result_count": len(items)},
    )
    return KnowledgeBaseListResponse(items=[_item(item) for item in items])


@app.get("/api/admin/documents/{document_id}")
async def api_get_document(document_id: str, current_user: KbReader, session: Session):
    item = await _require_document(session, document_id, current_user)
    await append_audit_event(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        source="api",
        action="document.read",
        resource_type="document",
        resource_id=document_id,
        outcome="success",
        request_id=request_id_var.get(),
    )
    return {"item": _item(item)}


@app.get("/api/admin/audit-events", response_model=AuditEventListResponse)
async def api_list_audit_events(
    current_user: AuditReader,
    session: Session,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=512),
    action: str | None = Query(default=None, max_length=128),
    outcome: Literal["success", "failure", "denied"] | None = None,
    actor_id: str | None = Query(default=None, max_length=128),
):
    try:
        items, next_cursor = await list_audit_events(
            session,
            tenant_id=current_user.tenant_id,
            limit=limit,
            cursor=cursor,
            action=action,
            outcome=outcome,
            actor_id=actor_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await append_audit_event(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        source="api",
        action="audit.events_read",
        resource_type="audit_event_collection",
        outcome="success",
        request_id=request_id_var.get(),
        metadata={"result_count": len(items)},
    )
    return AuditEventListResponse(items=[AuditEventItem(**item) for item in items], next_cursor=next_cursor)


@app.post("/api/admin/documents/upload", response_model=UploadResponse)
async def upload_documents(
    current_user: KbWriter,
    session: Session,
    files: list[UploadFile] = File(...),
    title: str = Form(""),
    mode: Literal["rag", "graphrag", "hybrid"] = Form("rag"),
):
    await _rate_limit(current_user, "upload")
    if not files or len(files) > settings.upload.max_files_per_request:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件数量无效")
    created: list[KnowledgeBaseItem] = []
    for upload in files:
        file_name = Path(upload.filename or "").name
        extension = normalized_extension(file_name)
        document_id = uuid.uuid4().hex
        target = document_path(document_id, file_name)
        try:
            file_size, checksum = await stream_upload(upload, target, max_bytes=settings.upload.max_file_size_bytes)
            validate_file_signature(target, extension)
            payload = {
                "id": document_id,
                "file_name": file_name,
                "title": title[:512] or Path(file_name).stem,
                "tenant_id": current_user.tenant_id,
                "owner_id": current_user.user_id,
                "acl": ["private"],
                "upload_time": utc_now(),
                "mode": mode,
                "file_path": str(target),
                "checksum": checksum,
            }
            item = await create_document_with_audit(
                session,
                actor_id=current_user.user_id,
                request_id=request_id_var.get(),
                payload=payload,
                metadata={"file_size": file_size, "mode": mode, "upload_method": "multipart"},
            )
            created.append(_item(item))
        except Exception:
            target.unlink(missing_ok=True)
            raise
    return UploadResponse(items=created)


@app.post("/api/admin/uploads/resumable/init", response_model=ResumableUploadInitResponse)
async def init_resumable_upload(payload: ResumableUploadInitRequest, current_user: KbWriter, session: Session):
    await _rate_limit(current_user, "upload")
    if payload.file_size > settings.upload.max_file_size_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="文件超过大小限制")
    upload_id = uuid.uuid4().hex
    upload_root = upload_session_dir(upload_id)
    (upload_root / "chunks").mkdir(parents=True, exist_ok=False)
    try:
        await create_upload_session_with_audit(
            session,
            {
            "id": upload_id,
            "file_name": payload.file_name,
            "file_size": payload.file_size,
            "title": payload.title,
            "mode": payload.mode,
            "tenant_id": current_user.tenant_id,
            "owner_id": current_user.user_id,
            "acl": ["private"],
            "chunk_size": RESUMABLE_CHUNK_SIZE,
            },
            actor_id=current_user.user_id,
            request_id=request_id_var.get(),
        )
    except Exception:
        remove_upload_session_files(upload_id)
        raise
    return ResumableUploadInitResponse(upload_id=upload_id, chunk_size=RESUMABLE_CHUNK_SIZE)


@app.get("/api/admin/uploads/resumable/{upload_id}/status", response_model=ResumableUploadStatusResponse)
async def resumable_upload_status(upload_id: str, current_user: KbWriter, session: Session):
    meta = await get_upload_session(session, upload_id, current_user.tenant_id, current_user.user_id)
    if meta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上传会话不存在")
    return ResumableUploadStatusResponse(
        upload_id=upload_id,
        uploaded_chunks=_uploaded_chunk_indexes(upload_id),
        chunk_size=meta.chunk_size,
        file_size=meta.file_size,
    )


@app.post("/api/admin/uploads/resumable/{upload_id}/chunk")
async def upload_resumable_chunk(
    upload_id: str,
    current_user: KbWriter,
    session: Session,
    chunk_index: int = Form(..., ge=0),
    chunk: UploadFile = File(...),
):
    meta = await get_upload_session(session, upload_id, current_user.tenant_id, current_user.user_id)
    if meta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上传会话不存在")
    expected_chunks = (meta.file_size + meta.chunk_size - 1) // meta.chunk_size
    if chunk_index >= expected_chunks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="分片索引超出范围")
    expected_size = meta.chunk_size
    if chunk_index == expected_chunks - 1:
        expected_size = meta.file_size - (chunk_index * meta.chunk_size)
    chunk_path = upload_session_dir(upload_id) / "chunks" / f"{chunk_index}.part"
    await stream_upload(chunk, chunk_path, max_bytes=meta.chunk_size, expected_bytes=expected_size)
    return {"success": True, "uploaded_chunks": _uploaded_chunk_indexes(upload_id)}


@app.post("/api/admin/uploads/resumable/complete", response_model=UploadResponse)
async def complete_resumable_upload(
    payload: ResumableUploadCompleteRequest,
    current_user: KbWriter,
    session: Session,
):
    meta = await get_upload_session(session, payload.upload_id, current_user.tenant_id, current_user.user_id)
    if meta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上传会话不存在")
    expected_chunks = (meta.file_size + meta.chunk_size - 1) // meta.chunk_size
    if _uploaded_chunk_indexes(payload.upload_id) != list(range(expected_chunks)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="分片未上传完整")
    document_id = uuid.uuid4().hex
    target = document_path(document_id, meta.file_name)
    checksum = combine_chunks(payload.upload_id, expected_chunks, target, meta.file_size)
    validate_file_signature(target, normalized_extension(meta.file_name))
    try:
        item = await create_document_with_audit(
            session,
            payload={
                "id": document_id,
                "file_name": meta.file_name,
                "title": meta.title or Path(meta.file_name).stem,
                "tenant_id": current_user.tenant_id,
                "owner_id": current_user.user_id,
                "acl": meta.acl,
                "upload_time": utc_now(),
                "mode": meta.mode,
                "file_path": str(target),
                "checksum": checksum,
            },
            actor_id=current_user.user_id,
            request_id=request_id_var.get(),
            metadata={"file_size": meta.file_size, "mode": meta.mode, "upload_method": "resumable"},
            upload_session=meta,
        )
    except Exception:
        target.unlink(missing_ok=True)
        raise
    remove_upload_session_files(payload.upload_id)
    return UploadResponse(items=[_item(item)])


def _ingest_mode(mode: str) -> str:
    return {"rag": "milvus", "graphrag": "graph", "hybrid": "mg"}[mode]


@app.post("/api/admin/documents/{document_id}/ingest", response_model=UploadResponse, status_code=202)
async def ingest_document(document_id: str, payload: IngestRequest, current_user: KbWriter, session: Session):
    item = await _require_document(session, document_id, current_user)
    if item["status"] in {"queued", "processing", "delete_queued"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="文档已有进行中的任务")
    mode = _ingest_mode(payload.mode)
    item = await update_document(
        session,
        document_id,
        current_user.tenant_id,
        status="queued",
        mode=payload.mode,
        error=None,
        ingest_progress=0,
        ingest_total=1,
        ingest_message="等待入库 Worker",
    )
    await _queue_document_job(
        session, item, operation="ingest", mode=mode, current_user=current_user
    )  # type: ignore[arg-type]
    return UploadResponse(items=[_item(item)])  # type: ignore[arg-type]


@app.post("/api/admin/documents/bulk/ingest", response_model=UploadResponse, status_code=202)
async def bulk_ingest_documents(payload: BulkIngestRequest, current_user: KbWriter, session: Session):
    items: list[KnowledgeBaseItem] = []
    for document_id in dict.fromkeys(payload.ids):
        item = await _require_document(session, document_id, current_user)
        if item["status"] in {"queued", "processing", "delete_queued"}:
            continue
        updated = await update_document(
            session,
            document_id,
            current_user.tenant_id,
            status="queued",
            mode=payload.mode,
            error=None,
            ingest_message="等待入库 Worker",
        )
        await _queue_document_job(
            session,
            updated,
            operation="ingest",
            mode=_ingest_mode(payload.mode),
            current_user=current_user,
        )  # type: ignore[arg-type]
        items.append(_item(updated))  # type: ignore[arg-type]
    return UploadResponse(items=items)


async def _queue_delete(session: AsyncSession, item: dict[str, Any], current_user: CurrentUser) -> None:
    updated = await update_document(
        session,
        item["id"],
        item["tenant_id"],
        status="delete_queued",
        ingest_message="等待清理检索数据",
    )
    await _queue_document_job(
        session, updated, operation="delete", mode="mg", current_user=current_user
    )  # type: ignore[arg-type]


@app.delete("/api/admin/documents/{document_id}", response_model=DeleteResponse, status_code=202)
async def remove_document(document_id: str, current_user: KbDeleter, session: Session):
    item = await _require_document(session, document_id, current_user)
    await _queue_delete(session, item, current_user)
    return DeleteResponse(success=True)


@app.post("/api/admin/documents/bulk/delete", response_model=DeleteResponse, status_code=202)
async def bulk_remove_documents(payload: BulkDeleteRequest, current_user: KbDeleter, session: Session):
    queued = 0
    for document_id in dict.fromkeys(payload.ids):
        item = await get_document(session, document_id, current_user.tenant_id)
        if item is None or item["status"] == "delete_queued":
            continue
        await _queue_delete(session, item, current_user)
        queued += 1
    return DeleteResponse(success=queued > 0)


@app.delete("/api/admin/knowledge-base", response_model=DeleteResponse, status_code=202)
async def remove_knowledge_base(current_user: KbDeleter, session: Session):
    items = await list_documents(session, current_user.tenant_id)
    for item in items:
        if item["status"] != "delete_queued":
            await _queue_delete(session, item, current_user)
    return DeleteResponse(success=bool(items))


@app.get("/api/admin/jobs/{job_id}", response_model=JobResponse)
async def get_job_status(job_id: str, current_user: KbReader, session: Session):
    job = await session.scalar(
        select(IngestionJobRecord).where(
            IngestionJobRecord.id == job_id,
            IngestionJobRecord.tenant_id == current_user.tenant_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return JobResponse(
        id=job.id,
        document_id=job.document_id,
        operation=job.operation,
        mode=job.mode,
        status=job.status,
        attempts=job.attempts,
        error=job.error,
    )


@app.get("/api/health/live")
async def liveness():
    return {"status": "ok"}


async def _readiness_payload() -> tuple[bool, dict[str, Any]]:
    checks: dict[str, Any] = {}
    try:
        checks["redis"] = bool(redis_conn and await redis_conn.ping())
    except Exception:
        checks["redis"] = False
    try:
        async with SessionFactory() as session:
            checks["database"] = (await session.execute(text("SELECT 1"))).scalar_one() == 1
    except Exception:
        checks["database"] = False
    checks["checkpointer"] = global_checkpointer is not None
    external = await run_checks({"milvus", "neo4j", "ollama", "mcp-rag"})
    checks.update({result.name: result.ok for result in external})
    return all(checks.values()), checks


@app.get("/api/health/ready")
@app.get("/api/health")
async def readiness():
    ready, checks = await _readiness_payload()
    return JSONResponse(
        status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "ok" if ready else "not_ready", "checks": checks},
    )


app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets"), check_dir=False), name="assets")


@app.get("/")
async def get_frontend():
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX)
    return HTMLResponse("<html><body><h1>Frontend not built</h1></body></html>", status_code=503)


@app.get("/{path:path}")
async def spa_fallback(path: str):
    if path.startswith("api/"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX)
    return HTMLResponse("<html><body><h1>Frontend not built</h1></body></html>", status_code=503)


if __name__ == "__main__":
    uvicorn.run(
        "multi_domain_enterprise_project.main:app",
        host="0.0.0.0",
        port=8080,
        reload=os.getenv("UVICORN_RELOAD") == "1",
    )
