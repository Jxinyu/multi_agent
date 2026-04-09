import asyncio
import json
import os
import logging
from typing import Optional, List, Any

from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

from redis.asyncio import Redis
from starlette.responses import StreamingResponse

from config import settings
from multi_domain_enterprise_project.agent.agent_main import run_agent, run_agent_stream
from langgraph.checkpoint.redis import AsyncRedisSaver
import redis

# 设置代理白名单
os.environ["NO_PROXY"] = "localhost,127.0.0.1,modelscope.net,bigmodel.cn,xiaoai.plus"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("watchfiles.main").setLevel(logging.WARNING)
logging.getLogger("redisvl.index.index").setLevel(logging.WARNING)
logging.getLogger("langgraph.checkpoint.redis.aio").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("mcp.client.streamable_http").setLevel(logging.WARNING)

# 全局变量
redis_conn = None
global_checkpointer = None


async def lifespan(app: FastAPI):
    global redis_conn, global_checkpointer

    redis_url = settings.llm_key.redis  # "redis://localhost:6379/0"

    # 1. 建立业务用 Redis 连接池，并正确赋值给全局变量 redis_conn！
    redis_conn = Redis.from_url(redis_url, decode_responses=False)
    app.state.redis = redis_conn

    # 2. 正确初始化 LangGraph 的 Redis Checkpointer
    # 使用官方推荐的 from_conn_string 方法，并在 lifespan 中保持上下文打开
    async with AsyncRedisSaver.from_conn_string(redis_url) as checkpointer:
        # 初次使用 Redis Checkpoint 需要调用 asetup() 初始化底层的 RediSearch 索引
        await checkpointer.asetup()

        global_checkpointer = checkpointer
        logger.info("✅ Redis Checkpointer 初始化成功！")

        # 挂起，等待 FastAPI 服务运行（此时 Checkpointer 的连接会保持开启）
        yield

    # 3. 服务关闭时，释放全局业务 Redis 连接
    # 注意：checkpointer 的连接会在退出上述 async with 上下文时自动安全释放
    if redis_conn:
        await redis_conn.aclose()
    logger.info("🛑 服务关闭，Redis 连接池已释放。")


app = FastAPI(title="企业多智能体助手 (FastAPI + pg)", lifespan=lifespan)


# --- 定义异步 Worker 任务 ---

async def write_to_redis_cache(thread_id: str, query: str):
    """写入 Redis 临时缓存"""
    try:
        # 这里使用同一个 redis 连接池，真实场景可以存入特定的业务 DB
        cache_key = f"cache:request:{thread_id}"
        await redis_conn.setex(cache_key, 3600, query)  # 缓存 1 小时
        logger.info(f"⚡[Fast Response] 请求已快速写入 Redis 临时缓存: {thread_id}")
    except Exception as e:
        logger.error(f"❌ 写入 Redis 缓存失败: {e}")


async def worker_write_to_postgres(thread_id: str, query: str):
    """消费者 Worker 写入 PostgreSQL 请求表 (替代 Kafka)"""
    try:
        # 模拟 I/O 延迟
        await asyncio.sleep(0.5)
        # TODO: 在此处编写你的 asyncpg 或 SQLAlchemy 异步插入 PostgreSQL 的逻辑
        # db.execute("INSERT INTO chat_requests (thread_id, query) VALUES ($1, $2)", thread_id, query)
        logger.info(f"💾 [Worker] 异步持久化到 PostgreSQL 请求表成功: {thread_id}")
    except Exception as e:
        logger.error(f"❌ 写入 PG 请求表失败: {e}")


# ----------------------------------------------------


# 定义 API 数据模型
class ChatRequest(BaseModel):
    query: str
    thread_id: str


class ChatResponse(BaseModel):
    status: str  # "completed" (回答完毕) 或 "waiting_for_user" (等待人工补充)
    message: str
    references: Optional[List[Any]] = None


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, background_tasks: BackgroundTasks):
    """
   核心对话接口：API Gateway
   完全按照架构图进行分流：
   1. 快速响应：将写入 Redis 缓存和 PG 落库交给 BackgroundTasks
   2. LangGraph 执行：直接进入 Graph 推流，读写 Redis Checkpoint
   """

    # ==========================================
    # 架构左侧分支：快速响应与后台持久化 (无 Kafka 实现)
    # ==========================================
    # FastAPI 会在后台独立协程执行这些任务，不会阻塞当前请求的流式返回
    background_tasks.add_task(write_to_redis_cache, request.thread_id, request.query)
    background_tasks.add_task(worker_write_to_postgres, request.thread_id, request.query)

    # ==========================================
    # 架构右侧分支：LangGraph 执行与 Redis Checkpoint
    # ==========================================
    config = {
        "configurable": {
            "thread_id": request.thread_id,
            "user_info": {"user_id": "123123", "position": "CEO", "department": "老板"}
        }
    }

    async def event_generator():
        # 调用流式引擎 (内部将使用 global_checkpointer 即 Redis)
        async for chunk in run_agent_stream(
                query=request.query,
                config=config,
                checkpointer=global_checkpointer
        ):
            # 将字典转为 Server-Sent Events 标准格式: "data: {}\n\n"
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    # 使用 text/event-stream 返回流式响应
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/")
async def get_chat_ui():
    """
    前端页面包含流式解析逻辑与动态状态条UI
    """
    html_content = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>企业多智能体大群 - 动态展示平台</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            .chat-box { height: calc(100vh - 160px); }
            .spinner { border: 3px solid #f3f3f3; border-top: 3px solid #3498db; border-radius: 50%; width: 18px; height: 18px; animation: spin 1s linear infinite; display: inline-block; vertical-align: middle;}
            /* 状态条独占 spinner 样式 */
            .status-spinner { border: 2px solid rgba(59, 130, 246, 0.2); border-top: 2px solid #2563eb; width: 14px; height: 14px;}
            @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
            ::-webkit-scrollbar { width: 6px; }
            ::-webkit-scrollbar-track { background: transparent; }
            ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 3px; }
        </style>
    </head>
    <body class="bg-gray-50 flex flex-col h-screen">
        <header class="bg-blue-600 text-white p-4 shadow-md flex justify-between items-center">
            <h1 class="text-xl font-bold">🤖 企业多智能体核心调度系统</h1>
            <span id="thread-display" class="text-sm bg-blue-700 px-3 py-1 rounded-full text-blue-100 font-mono"></span>
        </header>

        <main id="chat-container" class="flex-1 chat-box overflow-y-auto p-4 space-y-4 max-w-4xl mx-auto w-full">
            <div class="flex items-start">
                <div class="bg-white border border-gray-200 p-4 rounded-lg rounded-tl-none shadow-sm max-w-[80%]">
                    <p class="text-gray-800 text-sm">你好，我是企业综合 AI 调度中枢。请问有什么可以帮你？</p>
                </div>
            </div>
        </main>

        <footer class="bg-white border-t border-gray-200 p-4">
            <div class="max-w-4xl mx-auto flex gap-2">
                <input type="text" id="user-input" class="flex-1 border border-gray-300 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm" placeholder="输入你想咨询的业务问题..." onkeypress="if(event.key === 'Enter') sendMessage()">
                <button onclick="sendMessage()" id="send-btn" class="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded-lg font-medium transition-colors focus:outline-none flex items-center justify-center min-w-[100px]">
                    发送
                </button>
            </div>
        </footer>

        <script>
            const threadId = 'thread_' + Math.random().toString(36).substr(2, 9);
            document.getElementById('thread-display').innerText = "Session: " + threadId;

            const chatContainer = document.getElementById('chat-container');
            const userInput = document.getElementById('user-input');
            const sendBtn = document.getElementById('send-btn');

            // 绘制气泡消息
            function appendMessage(role, text, references = null, isStatus = false) {
                const wrapper = document.createElement('div');
                wrapper.className = role === 'user' ? 'flex items-start justify-end' : 'flex items-start';

                let boxClass = role === 'user' 
                    ? 'bg-blue-600 text-white p-4 rounded-lg rounded-tr-none shadow-sm max-w-[80%]' 
                    : isStatus 
                        ? 'bg-amber-100 border border-amber-300 text-amber-900 p-4 rounded-lg rounded-tl-none shadow-sm max-w-[80%] font-medium'
                        : 'bg-white border border-gray-200 text-gray-800 p-4 rounded-lg rounded-tl-none shadow-sm max-w-[80%]';

                let html = `<div class="${boxClass}"><div class="text-sm whitespace-pre-wrap leading-relaxed">${text}</div>`;

                if (references && references.length > 0) {
                    html += `<div class="mt-3 pt-3 border-t border-gray-200 text-xs text-gray-500"><strong class="text-gray-600">📎 引用来源:</strong><ul class="list-disc pl-4 mt-1">`;
                    references.forEach(ref => { html += `<li>${ref}</li>`; });
                    html += `</ul></div>`;
                }

                html += `</div>`;
                wrapper.innerHTML = html;
                chatContainer.appendChild(wrapper);
                chatContainer.scrollTop = chatContainer.scrollHeight;
            }

            // --- 动态状态条管理 ---
            function createStatusBox(statusId) {
                const wrapper = document.createElement('div');
                wrapper.id = statusId;
                wrapper.className = 'flex items-start my-2';
                wrapper.innerHTML = `
                    <div class="bg-blue-50 border border-blue-200 text-blue-800 px-4 py-3 rounded-lg rounded-tl-none shadow-sm max-w-[80%] flex items-center gap-3 transition-all duration-300">
                        <span class="spinner status-spinner"></span>
                        <span id="${statusId}-text" class="text-sm font-medium animate-pulse">系统正在启动调度器...</span>
                    </div>`;
                chatContainer.appendChild(wrapper);
                chatContainer.scrollTop = chatContainer.scrollHeight;
            }

            function updateStatusBox(statusId, newText) {
                const textEl = document.getElementById(`${statusId}-text`);
                if(textEl) textEl.innerText = newText;
            }

            function removeStatusBox(statusId) {
                const box = document.getElementById(statusId);
                if(box) box.remove();
            }

            function setBtnLoading(isLoading) {
                if (isLoading) {
                    sendBtn.innerHTML = '<span class="spinner" style="margin-right:0;"></span>';
                    sendBtn.disabled = true;
                    sendBtn.classList.add('opacity-75', 'cursor-not-allowed');
                } else {
                    sendBtn.innerHTML = '发送';
                    sendBtn.disabled = false;
                    sendBtn.classList.remove('opacity-75', 'cursor-not-allowed');
                }
            }

            async function sendMessage() {
                const query = userInput.value.trim();
                if (!query) return;

                appendMessage('user', query);
                userInput.value = '';
                setBtnLoading(true);

                const statusId = 'status-' + Date.now();
                createStatusBox(statusId); // 生成动态进度条UI

                try {
                    // 发起 Fetch 请求并接入流式解析
                    const response = await fetch('/api/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ query: query, thread_id: threadId })
                    });

                    // 使用 Reader 逐步读取数据流
                    const reader = response.body.getReader();
                    const decoder = new TextDecoder();
                    let buffer = "";

                    while (true) {
                        const { done, value } = await reader.read();
                        if (done) break;

                        buffer += decoder.decode(value, { stream: true });
                        const lines = buffer.split("\\n\\n");
                        buffer = lines.pop(); // 保留不完整的最后一块

                        for (const line of lines) {
                            if (line.startsWith("data: ")) {
                                const dataStr = line.substring(6);
                                const data = JSON.parse(dataStr);

                                // 状态路由分支
                                if (data.type === 'status') {
                                    updateStatusBox(statusId, data.message); // 更新前端动态提示字
                                } else if (data.type === 'complete') {
                                    removeStatusBox(statusId);
                                    appendMessage('ai', data.message, data.references);
                                } else if (data.type === 'interrupt') {
                                    removeStatusBox(statusId);
                                    appendMessage('ai', data.message, null, true);
                                } else if (data.type === 'error') {
                                    removeStatusBox(statusId);
                                    appendMessage('ai', '❌ ' + data.message, null, true);
                                }
                            }
                        }
                    }

                } catch (error) {
                    removeStatusBox(statusId);
                    appendMessage('ai', '❌ 网络请求流异常: ' + error.message, null, true);
                } finally {
                    setBtnLoading(false);
                }
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
