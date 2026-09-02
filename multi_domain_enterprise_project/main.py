from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.redis import AsyncRedisSaver
from prometheus_client import make_asgi_app
from pydantic import BaseModel, Field, field_validator
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings, validate_runtime_settings
from multi_domain_enterprise_project.agent.agent_main import run_agent_stream
from multi_domain_enterprise_project.api.authentication import router as authentication_router
from multi_domain_enterprise_project.api.conversations import router as conversations_router
from multi_domain_enterprise_project.api.enterprise import router as enterprise_router
from multi_domain_enterprise_project.api.files import router as files_router
from multi_domain_enterprise_project.api.health import router as health_router
from multi_domain_enterprise_project.api.jobs import router as jobs_router
from multi_domain_enterprise_project.api.jobs import user_router as user_jobs_router
from multi_domain_enterprise_project.api.knowledge_runtime import router as knowledge_runtime_router
from multi_domain_enterprise_project.api.members import router as members_router
from multi_domain_enterprise_project.api.platform import router as platform_router
from multi_domain_enterprise_project.api.security import router as security_router
from multi_domain_enterprise_project.api.worker_runtime import router as worker_runtime_router
from multi_domain_enterprise_project.core.audit import (
    append_audit_event,
    create_document_with_audit,
    create_job_with_audit,
    create_upload_session_with_audit,
)
from multi_domain_enterprise_project.core.auth import (
    CurrentUser,
    require_permissions,
)
from multi_domain_enterprise_project.core.chat import ChatRequest, build_attachment_context
from multi_domain_enterprise_project.core.database import (
    SessionFactory,
    append_conversation_message,
    close_database,
    ensure_conversation,
    finish_conversation_turn,
    get_document,
    get_session,
    get_upload_session,
    init_database,
    list_documents,
    update_document,
    update_job,
    utc_now,
)
from multi_domain_enterprise_project.core.document_views import read_document_preview
from multi_domain_enterprise_project.core.jobs import enqueue_job, ensure_job_group
from multi_domain_enterprise_project.core.observability import (
    RequestContextMiddleware,
    configure_logging,
    configure_tracing,
    request_id_var,
)
from multi_domain_enterprise_project.core.search import (
    cache_search_evidence,
    get_cached_search_evidence,
    parse_retrieval_context,
)
from multi_domain_enterprise_project.core.storage import (
    combine_chunks,
    document_path,
    ensure_storage_roots,
    normalized_extension,
    remove_upload_session_files,
    stream_upload,
    upload_session_dir,
    validate_file_signature,
)
from multi_domain_enterprise_project.core.user_views import SearchEvidenceItem, SearchRequest, SearchResponse
from multi_domain_enterprise_project.rag.authorization import RetrievalAuthorization, is_metadata_authorized
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_conn
    validate_runtime_settings(settings)
    ensure_storage_roots()
    await init_database()

    redis_conn = Redis.from_url(settings.llm_key.redis, decode_responses=False)
    await redis_conn.ping()
    await ensure_job_group(redis_conn)
    app.state.redis = redis_conn

    async with AsyncRedisSaver.from_conn_string(settings.llm_key.redis) as checkpointer:
        await checkpointer.asetup()
        app.state.checkpointer = checkpointer
        logger.info("应用依赖初始化完成")
        yield

    app.state.checkpointer = None
    await redis_conn.aclose()
    redis_conn = None
    await close_database()
    logger.info("应用资源已释放")


app = FastAPI(title="企业多智能体助手", version="1.0.0", lifespan=lifespan)
app.include_router(authentication_router)
app.include_router(conversations_router)
app.include_router(enterprise_router)
app.include_router(files_router)
app.include_router(health_router)
app.include_router(jobs_router)
app.include_router(user_jobs_router)
app.include_router(knowledge_runtime_router)
app.include_router(members_router)
app.include_router(platform_router)
app.include_router(security_router)
app.include_router(worker_runtime_router)
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


class DocumentDetailResponse(BaseModel):
    item: KnowledgeBaseItem
    preview: str | None = None
    preview_truncated: bool = False


class UploadResponse(BaseModel):
    item: KnowledgeBaseItem | None = None
    items: list[KnowledgeBaseItem] | None = None
    job_ids: list[str] = Field(default_factory=list)


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


Session = Annotated[AsyncSession, Depends(get_session)]
ChatUser = Annotated[CurrentUser, Depends(require_permissions("chat:use"))]
KbReader = Annotated[CurrentUser, Depends(require_permissions("kb:read"))]
KbWriter = Annotated[CurrentUser, Depends(require_permissions("kb:write"))]
KbDeleter = Annotated[CurrentUser, Depends(require_permissions("kb:delete"))]


def _item(payload: dict[str, Any]) -> KnowledgeBaseItem:
    return KnowledgeBaseItem(**payload)


async def _require_document(session: AsyncSession, document_id: str, user: CurrentUser) -> dict[str, Any]:
    item = await get_document(session, document_id, user.tenant_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return item


async def _document_detail(item: dict[str, Any]) -> DocumentDetailResponse:
    preview, truncated = await read_document_preview(
        item,
        max_chars=settings.retrieval.max_context_chars,
    )
    return DocumentDetailResponse(item=_item(item), preview=preview, preview_truncated=truncated)


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


async def _queue_document_job(
    session: AsyncSession,
    item: dict[str, Any],
    *,
    operation: str,
    mode: str,
    current_user: CurrentUser,
) -> str:
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
    return job_id


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest, current_user: ChatUser, session: Session):
    await _rate_limit(current_user, "chat")
    chat_request_id = request_id_var.get()
    title = " ".join(request.query.split())[:80] or "新会话"
    conversation = await ensure_conversation(
        session,
        thread_id=request.thread_id,
        tenant_id=current_user.tenant_id,
        owner_id=current_user.user_id,
        title=title,
        attachment_count=len(request.attachments),
    )
    await append_conversation_message(
        session,
        conversation_id=conversation["id"],
        role="user",
        content=request.query,
        attachments=[{"name": item.name, "mime_type": item.mime_type} for item in request.attachments],
    )
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

    checkpointer = getattr(app.state, "checkpointer", None)

    async def event_generator():
        if checkpointer is None:
            async with SessionFactory() as audit_session:
                await finish_conversation_turn(
                    audit_session,
                    conversation_id=conversation["id"],
                    status="failed",
                    role="error",
                    content="会话服务未就绪",
                )
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
            attachment_context, names = await build_attachment_context(request.attachments)
            if names:
                yield f"data: {json.dumps({'type': 'status', 'message': f'已解析 {len(names)} 个附件'}, ensure_ascii=False)}\n\n"
            query = request.query
            if attachment_context:
                query = f"{query}\n\n【附件解析内容】\n{attachment_context}\n\n请结合附件内容回答。"
            terminal_chunk: dict[str, Any] | None = None
            async for chunk in run_agent_stream(query=query, config=config, checkpointer=checkpointer):
                if chunk.get("type") in {"complete", "interrupt", "error"}:
                    terminal_chunk = chunk
                    continue
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            if terminal_chunk is None:
                terminal_chunk = {"type": "error", "message": "请求处理失败，请稍后重试", "references": []}
            async with SessionFactory() as audit_session:
                terminal_type = terminal_chunk.get("type")
                if terminal_type == "complete":
                    action, outcome = "chat.completed", "success"
                    conversation_status, message_role = "completed", "assistant"
                elif terminal_type == "interrupt":
                    action, outcome = "chat.waiting_input", "success"
                    conversation_status, message_role = "waiting", "assistant"
                else:
                    action, outcome = "chat.failed", "failure"
                    conversation_status, message_role = "failed", "error"
                terminal_message = str(terminal_chunk.get("message") or "请求处理失败，请稍后重试")
                terminal_references = [str(item) for item in terminal_chunk.get("references", [])]
                await finish_conversation_turn(
                    audit_session,
                    conversation_id=conversation["id"],
                    status=conversation_status,
                    role=message_role,
                    content=terminal_message,
                    references=terminal_references,
                )
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
            yield f"data: {json.dumps(terminal_chunk, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            async with SessionFactory() as audit_session:
                await finish_conversation_turn(
                    audit_session,
                    conversation_id=conversation["id"],
                    status="cancelled",
                )
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
                await finish_conversation_turn(
                    audit_session,
                    conversation_id=conversation["id"],
                    status="failed",
                    role="error",
                    content=str(exc.detail),
                )
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
                await finish_conversation_turn(
                    audit_session,
                    conversation_id=conversation["id"],
                    status="failed",
                    role="error",
                    content="请求处理失败，请稍后重试",
                )
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
    try:
        context = await retrieve_service(
            query_str=request.query,
            title=request.title,
            tenant_id=current_user.tenant_id,
            user_id=current_user.user_id,
            acl_list=current_user.groups,
            mode=request.mode,
        )
    except (ConnectionError, TimeoutError) as exc:
        logger.warning("检索依赖不可用: %s", type(exc).__name__)
        await append_audit_event(
            session,
            tenant_id=current_user.tenant_id,
            actor_id=current_user.user_id,
            source="api",
            action="search.failed",
            resource_type="knowledge_index",
            outcome="failure",
            request_id=request_id_var.get(),
            metadata={"error_type": type(exc).__name__, "mode": request.mode},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="检索依赖暂不可用，请稍后重试",
        ) from exc
    items = parse_retrieval_context(context)
    evidence_items = [SearchEvidenceItem(**item) for item in items]
    if redis_conn is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="证据缓存服务未初始化")
    await cache_search_evidence(
        redis_conn,
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        items=[item.model_dump() for item in evidence_items],
        ttl_seconds=settings.retrieval.evidence_cache_ttl_seconds,
    )
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
    return SearchResponse(items=evidence_items, mode=request.mode, elapsed_ms=elapsed_ms)


@app.get("/api/search/evidence/{evidence_id}", response_model=SearchEvidenceItem)
async def api_get_search_evidence(evidence_id: str, current_user: KbReader, session: Session):
    if len(evidence_id) != 16 or any(character not in "0123456789abcdef" for character in evidence_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="证据不存在或已过期")
    if redis_conn is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="证据缓存服务未初始化")
    item = await get_cached_search_evidence(
        redis_conn,
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        evidence_id=evidence_id,
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="证据不存在或已过期")
    await append_audit_event(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        source="api",
        action="search.evidence_read",
        resource_type="search_evidence",
        resource_id=evidence_id,
        outcome="success",
        request_id=request_id_var.get(),
    )
    return SearchEvidenceItem(**item)


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


@app.get("/api/documents/{document_id}", response_model=DocumentDetailResponse)
async def api_get_user_document(document_id: str, current_user: KbReader, session: Session):
    item = await get_document(session, document_id, current_user.tenant_id)
    scope = RetrievalAuthorization(
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        acl=tuple(current_user.groups),
    )
    if item is None or not is_metadata_authorized(item, scope):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在或无权访问")
    detail = await _document_detail(item)
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
        metadata={"preview_available": detail.preview is not None},
    )
    return detail


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


@app.get("/api/admin/documents/{document_id}", response_model=DocumentDetailResponse)
async def api_get_document(document_id: str, current_user: KbReader, session: Session):
    item = await _require_document(session, document_id, current_user)
    detail = await _document_detail(item)
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
    return detail


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
    job_id = await _queue_document_job(
        session, item, operation="ingest", mode=mode, current_user=current_user
    )  # type: ignore[arg-type]
    return UploadResponse(items=[_item(item)], job_ids=[job_id])  # type: ignore[arg-type]


@app.post("/api/admin/documents/bulk/ingest", response_model=UploadResponse, status_code=202)
async def bulk_ingest_documents(payload: BulkIngestRequest, current_user: KbWriter, session: Session):
    items: list[KnowledgeBaseItem] = []
    job_ids: list[str] = []
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
        job_id = await _queue_document_job(
            session,
            updated,
            operation="ingest",
            mode=_ingest_mode(payload.mode),
            current_user=current_user,
        )  # type: ignore[arg-type]
        items.append(_item(updated))  # type: ignore[arg-type]
        job_ids.append(job_id)
    return UploadResponse(items=items, job_ids=job_ids)


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
