from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

import uvicorn
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from starlette.responses import StreamingResponse

from config import settings
from langgraph.checkpoint.redis import AsyncRedisSaver
from multi_domain_enterprise_project.agent.agent_main import run_agent_stream
from multi_domain_enterprise_project.core.task_state import TaskStatus
from multi_domain_enterprise_project.rag.documentParser.parser_route import DocumentParserRouter
from multi_domain_enterprise_project.rag.document_in_database import insert_document
from multi_domain_enterprise_project.rag.kb_admin import (
    KnowledgeDocument,
    clear_knowledge_base,
    create_document_id,
    delete_document,
    ensure_kb_root,
    load_registry,
    patch_document,
    upsert_document,
)

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,modelscope.net,bigmodel.cn,xiaoai.plus")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("watchfiles.main").setLevel(logging.WARNING)
logging.getLogger("redisvl.index.index").setLevel(logging.WARNING)
logging.getLogger("langgraph.checkpoint.redis.aio").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("mcp.client.streamable_http").setLevel(logging.WARNING)

redis_conn: Redis | None = None
global_checkpointer = None

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
FRONTEND_INDEX = FRONTEND_DIST / "index.html"


async def lifespan(app: FastAPI):
    global redis_conn, global_checkpointer

    redis_url = settings.llm_key.redis
    redis_conn = Redis.from_url(redis_url, decode_responses=False)
    app.state.redis = redis_conn

    async with AsyncRedisSaver.from_conn_string(redis_url) as checkpointer:
        await checkpointer.asetup()
        global_checkpointer = checkpointer
        logger.info("Redis Checkpointer 初始化成功")
        yield

    if redis_conn:
        await redis_conn.aclose()
    logger.info("服务关闭，Redis 连接池已释放")


app = FastAPI(title="企业多智能体助手", lifespan=lifespan)


async def write_to_redis_cache(thread_id: str, query: str):
    try:
        cache_key = f"cache:request:{thread_id}"
        await redis_conn.setex(cache_key, 3600, query)  # type: ignore[union-attr]
    except Exception as exc:
        logger.error("写入 Redis 缓存失败: %s", exc)


async def worker_write_to_postgres(thread_id: str, query: str):
    try:
        await asyncio.sleep(0.5)
        logger.info("异步持久化请求成功: %s", thread_id)
    except Exception as exc:
        logger.error("写入 PG 请求表失败: %s", exc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AttachmentPayload(BaseModel):
    name: str
    mime_type: str
    data_base64: str


class ChatRequest(BaseModel):
    query: str
    thread_id: str
    attachments: list[AttachmentPayload] = Field(default_factory=list)


class ChatResponse(BaseModel):
    status: str
    message: str
    references: Optional[List[Any]] = None


class CurrentUser(BaseModel):
    user_id: str
    username: str
    tenant_id: str
    role: str
    permissions: list[str]


MOCK_CURRENT_USER = CurrentUser(
    user_id='user_admin_001',
    username='admin',
    tenant_id='tenant_default',
    role='admin',
    permissions=['kb:read', 'kb:write', 'kb:delete'],
)


def get_current_user() -> CurrentUser:
    return MOCK_CURRENT_USER


class CurrentUserResponse(BaseModel):
    user: CurrentUser


class KnowledgeBaseItem(BaseModel):
    id: str
    file_name: str
    title: str
    tenant_id: str
    owner_id: str
    acl: str
    upload_time: str
    mode: str
    file_path: str
    file_path_md: Optional[str] = None
    status: str = 'uploaded'
    chunk_count: int = 0
    error: Optional[str] = None
    ingest_progress: int = 0
    ingest_total: int = 0
    ingest_message: Optional[str] = None
    batch_id: Optional[str] = None


class KnowledgeBaseListResponse(BaseModel):
    items: list[KnowledgeBaseItem]


class KnowledgeBaseGetResponse(BaseModel):
    item: KnowledgeBaseItem


class IngestRequest(BaseModel):
    mode: str = Field(default='rag')


class BulkIngestRequest(BaseModel):
    ids: list[str]
    mode: str = Field(default='rag')


class BulkDeleteRequest(BaseModel):
    ids: list[str]


class UploadResponse(BaseModel):
    item: KnowledgeBaseItem | None = None
    items: list[KnowledgeBaseItem] | None = None


class ResumableUploadInitRequest(BaseModel):
    file_name: str
    file_size: int
    title: str = ''
    mode: str = 'rag'


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
    upload_id: str


class DeleteResponse(BaseModel):
    success: bool


RESUMABLE_CHUNK_SIZE = 2 * 1024 * 1024


def _upload_sessions_root() -> Path:
    return Path('data') / 'knowledge_base' / 'upload_sessions'


async def _load_item(doc_id: str) -> dict[str, Any] | None:
    return next((doc for doc in load_registry() if doc.get('id') == doc_id), None)


def _filter_items_for_user(items: list[dict[str, Any]], current_user: CurrentUser) -> list[dict[str, Any]]:
    return [item for item in items if item.get('tenant_id') == current_user.tenant_id]


def _ensure_user_can_access_item(item: dict[str, Any] | None, current_user: CurrentUser) -> dict[str, Any]:
    if item is None:
        raise HTTPException(status_code=404, detail='文档不存在')
    if item.get('tenant_id') != current_user.tenant_id:
        raise HTTPException(status_code=404, detail='文档不存在')
    return item


def _session_dir(upload_id: str) -> Path:
    if not upload_id.replace('-', '').replace('_', '').isalnum():
        raise HTTPException(status_code=400, detail='非法 upload_id')
    return _upload_sessions_root() / upload_id


def _session_meta_path(upload_id: str) -> Path:
    return _session_dir(upload_id) / 'meta.json'


def _load_upload_meta(upload_id: str, current_user: CurrentUser) -> dict[str, Any]:
    meta_path = _session_meta_path(upload_id)
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail='上传会话不存在')
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    if meta.get('tenant_id') != current_user.tenant_id or meta.get('owner_id') != current_user.user_id:
        raise HTTPException(status_code=404, detail='上传会话不存在')
    return meta


def _save_upload_meta(upload_id: str, meta: dict[str, Any]) -> None:
    session_dir = _session_dir(upload_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    _session_meta_path(upload_id).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')


def _uploaded_chunk_indexes(upload_id: str) -> list[int]:
    chunks_dir = _session_dir(upload_id) / 'chunks'
    if not chunks_dir.exists():
        return []
    indexes: list[int] = []
    for path in chunks_dir.glob('*.part'):
        try:
            indexes.append(int(path.stem))
        except ValueError:
            continue
    return sorted(indexes)


def _decode_attachment_data(data_base64: str) -> bytes:
    if "," in data_base64 and data_base64.startswith("data:"):
        data_base64 = data_base64.split(",", 1)[1]
    return base64.b64decode(data_base64)


def _attachment_suffix(name: str, mime_type: str) -> str:
    suffix = Path(name).suffix
    if suffix:
        return suffix
    if "pdf" in mime_type:
        return ".pdf"
    if "png" in mime_type:
        return ".png"
    if "jpeg" in mime_type or "jpg" in mime_type:
        return ".jpg"
    return ".bin"


async def build_attachment_context(attachments: list[AttachmentPayload]) -> tuple[str, list[str]]:
    if not attachments:
        return "", []
    router = DocumentParserRouter(mode="auto")
    sections: list[str] = []
    names: list[str] = []
    with tempfile.TemporaryDirectory(prefix="rag-upper-attachments-") as temp_dir:
        temp_dir_path = Path(temp_dir)
        for item in attachments:
            names.append(item.name)
            temp_path = temp_dir_path / f"{Path(item.name).stem[:64]}{_attachment_suffix(item.name, item.mime_type)}"
            temp_path.write_bytes(_decode_attachment_data(item.data_base64))
            parsed = await router.route_and_parse(str(temp_path))
            sections.append(f"### 附件: {item.name}\n{parsed}")
    return "\n\n".join(sections), names


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(write_to_redis_cache, request.thread_id, request.query)
    background_tasks.add_task(worker_write_to_postgres, request.thread_id, request.query)
    config: dict[str, Any] = {
        "configurable": {
            "thread_id": request.thread_id,
            "user_info": {"user_id": "123123", "position": "CEO", "department": "老板"},
            "task_status": TaskStatus.ROUTING.value,
        }
    }

    async def event_generator():
        if global_checkpointer is None:
            yield f"data: {json.dumps({'type': 'error', 'message': '检查点服务未初始化'}, ensure_ascii=False)}\n\n"
            return
        attachment_context = ""
        if request.attachments:
            yield f"data: {json.dumps({'type': 'status', 'message': f'正在解析 {len(request.attachments)} 个附件...'}, ensure_ascii=False)}\n\n"
            attachment_context, attachment_names = await build_attachment_context(request.attachments)
            if attachment_context:
                joined_names = "、".join(attachment_names)
                yield f"data: {json.dumps({'type': 'status', 'message': f'附件解析完成：{joined_names}'}, ensure_ascii=False)}\n\n"
        query_text = request.query
        if attachment_context:
            query_text = f"{request.query}\n\n【附件解析内容】\n{attachment_context}\n\n请结合附件内容回答用户问题。"
        async for chunk in run_agent_stream(query=query_text, config=config, checkpointer=global_checkpointer):
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/health")
async def api_health():
    return {"status": "ok"}


@app.get("/api/auth/me", response_model=CurrentUserResponse)
async def get_me(current_user: CurrentUser = Depends(get_current_user)):
    return CurrentUserResponse(user=current_user)


@app.get("/api/admin/documents", response_model=KnowledgeBaseListResponse)
async def list_documents(current_user: CurrentUser = Depends(get_current_user)):
    ensure_kb_root()
    items = _filter_items_for_user(load_registry(), current_user)
    return KnowledgeBaseListResponse(items=[KnowledgeBaseItem(**item) for item in items])


@app.get("/api/admin/documents/{doc_id}")
async def get_document(doc_id: str, current_user: CurrentUser = Depends(get_current_user)):
    item = _ensure_user_can_access_item(await _load_item(doc_id), current_user)
    return {"item": KnowledgeBaseItem(**item)}


@app.post("/api/admin/documents/upload", response_model=UploadResponse)
async def upload_document(
    files: list[UploadFile] = File(...),
    title: str = Form(''),
    mode: str = Form('rag'),
    current_user: CurrentUser = Depends(get_current_user),
):
    ensure_kb_root()
    created: list[KnowledgeBaseItem] = []
    for file in files:
        document_id = create_document_id()
        suffix = Path(file.filename or '').suffix or '.bin'
        file_name = file.filename or f'document{suffix}'
        stored_file = Path('data') / 'knowledge_base' / 'files' / f'{document_id}{suffix}'
        stored_file.parent.mkdir(parents=True, exist_ok=True)
        contents = await file.read()
        stored_file.write_bytes(contents)
        item = KnowledgeDocument(
            id=document_id,
            file_name=file_name,
            title=title or Path(file_name).stem,
            tenant_id=current_user.tenant_id,
            owner_id=current_user.user_id,
            acl='private',
            upload_time=_now_iso(),
            mode=mode,
            file_path=str(stored_file),
        )
        upsert_document(item)
        created.append(KnowledgeBaseItem(**item.__dict__))
    return UploadResponse(items=created)


@app.post("/api/admin/uploads/resumable/init", response_model=ResumableUploadInitResponse)
async def init_resumable_upload(payload: ResumableUploadInitRequest, current_user: CurrentUser = Depends(get_current_user)):
    ensure_kb_root()
    upload_id = create_document_id()
    meta = {
        'upload_id': upload_id,
        'file_name': payload.file_name,
        'file_size': payload.file_size,
        'title': payload.title,
        'mode': payload.mode,
        'tenant_id': current_user.tenant_id,
        'owner_id': current_user.user_id,
        'acl': 'private',
        'chunk_size': RESUMABLE_CHUNK_SIZE,
        'created_at': _now_iso(),
    }
    _save_upload_meta(upload_id, meta)
    (_session_dir(upload_id) / 'chunks').mkdir(parents=True, exist_ok=True)
    return ResumableUploadInitResponse(upload_id=upload_id, uploaded_chunks=[], chunk_size=RESUMABLE_CHUNK_SIZE)


@app.get("/api/admin/uploads/resumable/{upload_id}/status", response_model=ResumableUploadStatusResponse)
async def resumable_upload_status(upload_id: str, current_user: CurrentUser = Depends(get_current_user)):
    meta = _load_upload_meta(upload_id, current_user)
    return ResumableUploadStatusResponse(
        upload_id=upload_id,
        uploaded_chunks=_uploaded_chunk_indexes(upload_id),
        chunk_size=int(meta.get('chunk_size') or RESUMABLE_CHUNK_SIZE),
        file_size=int(meta.get('file_size') or 0),
    )


@app.post("/api/admin/uploads/resumable/{upload_id}/chunk")
async def upload_resumable_chunk(
    upload_id: str,
    chunk_index: int = Form(...),
    chunk: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
):
    _load_upload_meta(upload_id, current_user)
    chunks_dir = _session_dir(upload_id) / 'chunks'
    chunks_dir.mkdir(parents=True, exist_ok=True)
    chunk_path = chunks_dir / f'{chunk_index}.part'
    chunk_path.write_bytes(await chunk.read())
    return {'success': True, 'uploaded_chunks': _uploaded_chunk_indexes(upload_id)}


@app.post("/api/admin/uploads/resumable/complete", response_model=UploadResponse)
async def complete_resumable_upload(payload: ResumableUploadCompleteRequest, current_user: CurrentUser = Depends(get_current_user)):
    meta = _load_upload_meta(payload.upload_id, current_user)
    chunk_size = int(meta.get('chunk_size') or RESUMABLE_CHUNK_SIZE)
    file_size = int(meta.get('file_size') or 0)
    expected_chunks = max(1, (file_size + chunk_size - 1) // chunk_size)
    uploaded = set(_uploaded_chunk_indexes(payload.upload_id))
    missing = [index for index in range(expected_chunks) if index not in uploaded]
    if missing:
        raise HTTPException(status_code=409, detail={'message': '分片未上传完整', 'missing_chunks': missing})

    document_id = create_document_id()
    file_name = str(meta.get('file_name') or 'document.bin')
    suffix = Path(file_name).suffix or '.bin'
    stored_file = Path('data') / 'knowledge_base' / 'files' / f'{document_id}{suffix}'
    stored_file.parent.mkdir(parents=True, exist_ok=True)
    chunks_dir = _session_dir(payload.upload_id) / 'chunks'
    with stored_file.open('wb') as target:
        for index in range(expected_chunks):
            target.write((chunks_dir / f'{index}.part').read_bytes())

    item = KnowledgeDocument(
        id=document_id,
        file_name=file_name,
        title=str(meta.get('title') or Path(file_name).stem),
        tenant_id=current_user.tenant_id,
        owner_id=current_user.user_id,
        acl='private',
        upload_time=_now_iso(),
        mode=str(meta.get('mode') or 'rag'),
        file_path=str(stored_file),
    )
    upsert_document(item)
    try:
        import shutil
        shutil.rmtree(_session_dir(payload.upload_id), ignore_errors=True)
    except Exception:
        pass
    return UploadResponse(items=[KnowledgeBaseItem(**item.__dict__)])


@app.post("/api/admin/documents/{doc_id}/ingest", response_model=UploadResponse)
async def ingest_document(doc_id: str, payload: IngestRequest, current_user: CurrentUser = Depends(get_current_user)):
    _ensure_user_can_access_item(await _load_item(doc_id), current_user)
    patch_document(doc_id, status='processing', mode=payload.mode, error=None, ingest_progress=0, ingest_total=1, ingest_message='开始入库')
    refreshed = await _load_item(doc_id)
    try:
        mapped_mode = 'graph' if payload.mode == 'graphrag' else 'milvus' if payload.mode == 'rag' else payload.mode
        await insert_document(refreshed, mode=mapped_mode)  # type: ignore[arg-type]
        patch_document(doc_id, status='completed', chunk_count=max(1, int((refreshed or {}).get('chunk_count', 0) or 1)), ingest_progress=1, ingest_total=1, ingest_message='入库完成')
    except Exception as exc:
        patch_document(doc_id, status='error', error=str(exc), ingest_message='入库失败')
        raise HTTPException(status_code=500, detail=f'入库失败: {exc}')
    updated = await _load_item(doc_id)
    return UploadResponse(items=[KnowledgeBaseItem(**updated)])


@app.post("/api/admin/documents/bulk/ingest", response_model=UploadResponse)
async def bulk_ingest_documents(payload: BulkIngestRequest, current_user: CurrentUser = Depends(get_current_user)):
    items: list[KnowledgeBaseItem] = []
    for doc_id in payload.ids:
        try:
            response = await ingest_document(doc_id, IngestRequest(mode=payload.mode), current_user)
            items.extend(response.items or [])
        except HTTPException:
            continue
    return UploadResponse(items=items)


@app.delete("/api/admin/documents/{doc_id}", response_model=DeleteResponse)
async def remove_document(doc_id: str, current_user: CurrentUser = Depends(get_current_user)):
    _ensure_user_can_access_item(await _load_item(doc_id), current_user)
    if not delete_document(doc_id):
        raise HTTPException(status_code=404, detail='文档不存在')
    return DeleteResponse(success=True)


@app.post("/api/admin/documents/bulk/delete", response_model=DeleteResponse)
async def bulk_remove_documents(payload: BulkDeleteRequest, current_user: CurrentUser = Depends(get_current_user)):
    removed = 0
    for doc_id in payload.ids:
        try:
            _ensure_user_can_access_item(await _load_item(doc_id), current_user)
        except HTTPException:
            continue
        if delete_document(doc_id):
            removed += 1
    return DeleteResponse(success=removed > 0)


@app.delete("/api/admin/knowledge-base", response_model=DeleteResponse)
async def remove_knowledge_base(current_user: CurrentUser = Depends(get_current_user)):
    registry = load_registry()
    removed = 0
    for item in _filter_items_for_user(registry, current_user):
        if delete_document(item.get('id')):
            removed += 1
    return DeleteResponse(success=removed > 0)


@app.post("/api/admin/documents/{doc_id}/refresh")
async def refresh_document(doc_id: str, current_user: CurrentUser = Depends(get_current_user)):
    item = _ensure_user_can_access_item(await _load_item(doc_id), current_user)
    return {"item": KnowledgeBaseItem(**item)}


app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets"), check_dir=False), name="assets")


@app.get("/")
async def get_frontend():
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX)
    return HTMLResponse("<html><body><h1>Frontend not built</h1><p>Run `cd frontend && npm install && npm run build`.</p></body></html>")


@app.get("/{path:path}")
async def spa_fallback(path: str):
    if path.startswith("api/"):
        return {"detail": "Not Found"}
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX)
    return HTMLResponse("<html><body><h1>Frontend not built</h1><p>Run `cd frontend && npm install && npm run build`.</p></body></html>")


if __name__ == "__main__":
    uvicorn.run("multi_domain_enterprise_project.main:app", host="0.0.0.0", port=8080, reload=os.getenv("UVICORN_RELOAD") == "1")
