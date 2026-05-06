from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional, List

import uvicorn
from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from starlette.responses import StreamingResponse

from config import settings
from langgraph.checkpoint.redis import AsyncRedisSaver
from multi_domain_enterprise_project.agent.agent_main import run_agent_stream
from multi_domain_enterprise_project.core.task_state import TaskStatus
from multi_domain_enterprise_project.rag.documentParser.parser_route import DocumentParserRouter

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
    if "word" in mime_type:
        return ".docx"
    if "presentation" in mime_type or "powerpoint" in mime_type:
        return ".pptx"
    if "sheet" in mime_type or "excel" in mime_type:
        return ".xlsx"
    if "csv" in mime_type:
        return ".csv"
    if "json" in mime_type:
        return ".json"
    if mime_type.startswith("text/"):
        return ".txt"
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
            suffix = _attachment_suffix(item.name, item.mime_type)
            safe_name = Path(item.name).stem.replace(" ", "_")[:64] or "attachment"
            temp_path = temp_dir_path / f"{safe_name}{suffix}"

            try:
                logger.info("开始解析上传附件: name=%s mime=%s suffix=%s", item.name, item.mime_type, suffix)
                temp_path.write_bytes(_decode_attachment_data(item.data_base64))
                parsed = await router.route_and_parse(str(temp_path))
                logger.info("附件解析完成: name=%s chars=%s", item.name, len(parsed or ""))
                sections.append(f"### 附件: {item.name}\n{parsed}")
            except Exception as exc:
                logger.exception("附件解析失败: name=%s", item.name)
                sections.append(f"### 附件: {item.name}\n解析失败: {exc}")

    return "\n\n".join(sections), names


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, background_tasks: BackgroundTasks):
    logger.info(
        "收到聊天请求: thread_id=%s attachments=%s names=%s",
        request.thread_id,
        len(request.attachments),
        [item.name for item in request.attachments],
    )
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
            query_text = (
                f"{request.query}\n\n"
                f"【附件解析内容】\n{attachment_context}\n\n"
                f"请结合附件内容回答用户问题。"
            )

        async for chunk in run_agent_stream(
            query=query_text,
            config=config,
            checkpointer=global_checkpointer,
        ):
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/health")
async def api_health():
    return {"status": "ok"}


app.mount(
    "/assets",
    StaticFiles(directory=str(FRONTEND_DIST / "assets"), check_dir=False),
    name="assets",
)


@app.get("/")
async def get_frontend():
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX)
    return HTMLResponse(
        "<html><body><h1>Frontend not built</h1><p>Run `cd frontend && npm install && npm run build`.</p></body></html>"
    )


@app.get("/{path:path}")
async def spa_fallback(path: str):
    if path.startswith("api/"):
        return {"detail": "Not Found"}
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX)
    return HTMLResponse(
        "<html><body><h1>Frontend not built</h1><p>Run `cd frontend && npm install && npm run build`.</p></body></html>"
    )


if __name__ == "__main__":
    uvicorn.run(
        "multi_domain_enterprise_project.main:app",
        host="0.0.0.0",
        port=8080,
        reload=os.getenv("UVICORN_RELOAD") == "1",
    )
