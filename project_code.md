# Project Export: rag_upper

**Source Directory:** `D:\学习笔记\langchain\rag_upper`

---

## File: `t.py`

```py
t = {"query": "请用中文回答：1+1等于几？"}
print(t.get("quey", {}))







```

## File: `multi_domain_enterprise_project\main.py`

```py
import asyncio
import json
import os
import logging
from contextlib import asynccontextmanager
from typing import Optional, List, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

# 导入 LangGraph 核心组件
from langgraph.types import Command
# 导入 Redis 异步库及 LangGraph Redis Checkpointer
from redis.asyncio import Redis
from starlette.responses import StreamingResponse

from config import settings
from multi_domain_enterprise_project.agent.agent_main import run_agent, run_agent_stream
from multi_domain_enterprise_project.agent.supervisor_agent import create_graph
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
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
```

## File: `multi_domain_enterprise_project\__init__.py`

```py

```

## File: `multi_domain_enterprise_project\agent\agent_main.py`

```py
import asyncio
import datetime
import sys
import logging

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from config import settings
from multi_domain_enterprise_project.agent.supervisor_agent import create_graph

import os

os.environ["NO_PROXY"] = "localhost,127.0.0.1,modelscope.net,bigmodel.cn,xiaoai.plus"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_agent(query: str, config: dict, checkpointer) -> dict:
    """
    通用、无状态、防断网的 Agent 运行引擎。
    完美支持：单轮问答、多轮上下文对话、多轮连续人机协作(Interrupt)。
    """
    # 1. 初始化图 (如果 checkpointer 已传入，其实 create_graph 里的逻辑开销很小)
    agent = await create_graph(checkpointer)

    # 3. 探针：获取当前线程在数据库中的状态
    state = await agent.aget_state(config)

    try:
        # ==========================================
        # 核心路由逻辑：恢复中断 vs 正常追加对话
        # ==========================================
        if state and state.next:
            # 场景 A: 存在挂起的 Interrupt。说明用户现在的 query 是对 Agent 上一轮追问的【回复】
            logger.info(f"🧵[Thread {config['configurable']['thread_id']}] 从中断处恢复，提交人机协作数据: {query}")

            decision = {
                "content": query,
                "type": "approval",  # 配合你 tools 里的设计
            }
            # 使用 Command(resume) 精准恢复断点
            response = await agent.ainvoke(Command(resume=decision), config=config)

        else:
            # 场景 B: 正常的新问题 / 正常的多轮追加提问
            # 因为带有 thread_id，LangGraph 会自动把历史 message 拼在前面，不用你自己管理历史记录！
            logger.info(f"🧵 [Thread {config['configurable']['thread_id']}] 发起新一轮对话指令: {query}")

            response = await agent.ainvoke(
                {"messages": [{"role": "user", "content": query}]},
                config=config
            )

        # ==========================================
        # 结果处理逻辑：再次中断 vs 任务完成
        # ==========================================

        # 检查本轮图运行结束后，是否【再次】触发了人机交互 (多轮协作的关键)
        if '__interrupt__' in response:
            interrupt_data = response['__interrupt__'][0].value
            if interrupt_data.get('action') == 'human_decision':
                return {
                    "status": "waiting_for_user",
                    "message": interrupt_data['content'],
                    "references": []
                }

        # 如果没有 interrupt，说明 Graph 走到了 END，提取最终答案
        try:
            # 按照你 aggregator_agent 的标准格式提取
            final_reply = response['result']['最终回复']
            references = response['result'].get('参考资料', [])
            return {
                "status": "completed",
                "message": final_reply,
                "references": references
            }
        except KeyError:
            # 容错：如果没经过 aggregator (比如只有单节点返回)，安全提取最后一条消息
            last_msg = response['messages'][-1].content
            return {
                "status": "completed",
                "message": str(last_msg),
                "references": []
            }

    except Exception as e:
        logger.exception(f"❌ [Thread {config['configurable']['thread_id']}] 运行异常: {str(e)}")
        # 这里不要抛死，优雅地告诉前端发生了什么
        return {
            "status": "error",
            "message": f"系统开小差了，请稍后再试。错误信息: {str(e)}",
            "references": []
        }


async def run_agent_stream(query: str, config: dict, checkpointer):
    """
    流式、无状态、防断网的 Agent 运行引擎。
    实时推流当前执行的进度状态给前端。
    """
    agent = await create_graph(checkpointer)
    state = await agent.aget_state(config)

    if state and state.next:
        logger.info(f"🧵[Thread {config['configurable']['thread_id']}] 从中断处恢复...")
        decision = {"content": query, "type": "approval"}
        input_data = Command(resume=decision)
    else:
        logger.info(f"🧵 [Thread {config['configurable']['thread_id']}] 发起新一轮对话指令...")
        input_data = {"messages": [{"role": "user", "content": query}]}

    try:
        # 使用 stream_mode="updates" 逐个捕获图中节点的执行完成事件
        async for event in agent.astream(input_data, config=config, stream_mode="updates"):
            # event 的格式例如：{"supervisor": {"messages": [...]}}
            for node_name, node_state in event.items():
                # 根据节点名称，实时推流对应的状态文案
                if node_name == "supervisor":
                    yield {"type": "status", "message": "🧠 调度中枢正在分析意图并规划任务..."}
                elif node_name == "tools":
                    yield {"type": "status", "message": "🛠️ 正在为您分发任务至专属领域专家..."}
                elif node_name == "tech":
                    yield {"type": "status", "message": "💻 技术专家正在查阅系统操作指南..."}
                elif node_name == "hr":
                    yield {"type": "status", "message": "🧑‍💼 HR专家正在比对人事制度与离职流程..."}
                elif node_name == "finance":
                    yield {"type": "status", "message": "💰 财务专家正在核对财务报销规范..."}
                elif node_name == "legal":
                    yield {"type": "status", "message": "⚖️ 法务专家正在审查合规与法律条文..."}
                elif node_name == "aggregator":
                    yield {"type": "status", "message": "📝 信息合成中心正在汇编专家的最终解答..."}
                elif node_name == "audit":
                    feedback = node_state.get('audit_feedback')
                    if feedback:
                        yield {"type": "status", "message": "⚠️ 审计未通过，要求专家重新修正..."}
                    else:
                        yield {"type": "status", "message": "✅ 合规审计已通过，准备输出内容..."}

        # 图执行结束后（可能是 End，也可能是 Interrupt 挂起），提取最终状态
        final_state = await agent.aget_state(config)

        # 场景 A: 触发了人机交互挂起 (Interrupt)
        if final_state.next:
            interrupt_data = None

            # 🛠️ ：递归查找可能深藏在子 Agent (嵌套图) 中的中断数据
            def find_interrupt(snapshot):
                if (not snapshot) or (not hasattr(snapshot, 'tasks')) or (not snapshot.tasks):
                    return None
                for task in snapshot.tasks:
                    # 如果当前任务有中断，直接返回
                    if task.interrupts:
                        return task.interrupts[0].value
                    # 如果当前任务包含子图状态 (Sub-Graph)，向下一层穿透查找
                    if hasattr(task, 'state') and task.state:
                        res = find_interrupt(task.state)
                        if res:
                            return res
                return None

            # 提取中断数据
            interrupt_data = find_interrupt(final_state)

            if interrupt_data:
                logger.info(
                    f"⚠️ [Thread {config['configurable']['thread_id']}] 检测到子代理处于冻结状态，正在携带人类决策解冻...{interrupt_data}")
                action = interrupt_data.get('action')
                if action in ['human_decision', 'get_document']:
                    yield {
                        "type": "interrupt",
                        "message": interrupt_data['content'],
                        "references": []
                    }
                    return

        # 场景 B: 正常结束，提取最终回复
        result_data = final_state.values.get('result', {})
        if result_data:
            yield {
                "type": "complete",
                "message": result_data.get('最终回复', ''),
                "references": result_data.get('参考资料', [])
            }
        else:
            # 容错：兜底最后一条消息
            last_msg = final_state.values.get('messages', [])[-1].content
            yield {
                "type": "complete",
                "message": str(last_msg),
                "references": []
            }

    except Exception as e:
        logger.exception(f"❌ 运行异常: {str(e)}")
        yield {"type": "error", "message": f"系统开小差了，请稍后再试。错误信息: {str(e)}"}
```

## File: `multi_domain_enterprise_project\agent\aggregator_agent.py`

```py
import logging

from langchain.agents import create_agent
from langchain_core.runnables import RunnableConfig

from multi_domain_enterprise_project.core.model import qwen_model
from multi_domain_enterprise_project.core.self_state import State
from multi_domain_enterprise_project.core.sub_agent_output_format import SubAgentOutputFormat

logger = logging.getLogger(__name__)


async def aggregator_agent(state: State, config: RunnableConfig):
    """收集子Agent返回的答案，并进行整理。消除重复或冲突，合成一段逻辑连贯、主次分明的最终回答，并统一整理所有引用来源。"""
    # 获取所有子代理的输出
    content = state.sub_agent_response

    logger.info(f"【aggregator_agent 的输入】: {content.keys()}")

    system_prompt = """
# 角色定位
作为信息合成Agent，你的任务是将多个专业领域Agent针对同一用户问题的碎片化回答整合成一份逻辑连贯、主次分明、无重复冲突的最终答案，并统一整理所有引用来源。你本身不生成新信息，只对已有的子回复进行组织和优化。
# 遵守的规则
- 信息整合：
  - 将各个子回答中相关的内容按逻辑顺序组织，形成一个统一的答案。
  - 消除冗余信息：如果多个子回答提到同一事实，只保留一次，但可合并表达。
  - 调和潜在冲突：如果不同子回答存在明显矛盾，尝试判断是否因角度不同（如“规定A”与“例外B”），若无法调和，需如实说明不同观点，并指出需进一步核实。
- 保持专业语气：用词准确、中立，适合企业环境。
# 处理步骤
1. 阅读原始问题：理解用户的核心诉求，确定最终答案需要覆盖哪些方面。
2. 梳理子回答：
  - 提取每个子回答的关键信息点和对应的引用。
  - 识别不同回答中重复或重叠的部分，标记可合并的内容。
  - 检查是否存在冲突：例如一个说“必须提前3天”，另一个说“提前5天”。分析冲突原因（可能是不同政策版本或领域角度不同），若无法解决，则如实呈现。
3. 构建答案框架：根据问题逻辑，决定信息呈现顺序（例如按领域顺序、按流程步骤、按重要性等）。
4. 撰写整合答案：
  - 用连贯的语言将关键信息串联起来，避免生硬拼凑。
  - 在每个信息点后标注引用来源。若同一信息点来自多个来源，可一并列出。
  - 如有冲突，在答案中说明差异。
    """
    # 创建agent
    agent = create_agent(
        model=await qwen_model(),
        system_prompt=system_prompt,
        response_format=SubAgentOutputFormat,
    )

    response = await agent.ainvoke(input={"messages": [{"role": "user", "content": str(content)}]}, config=config)

    response = response['structured_response']

    logger.info(f"【aggregator Agent的回复】: {response.result[:10]}")

    return {
        "sub_agent_response": {
            "aggregator": {
                "回复内容": response.result,
                "参考资料": response.references
            },
        }
    }



```

## File: `multi_domain_enterprise_project\agent\audit_agent.py`

```py
import logging
from typing import Annotated, Dict, List

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from multi_domain_enterprise_project.core.model import qwen_model
from multi_domain_enterprise_project.core.self_state import State

logger = logging.getLogger(__name__)


class AuditOutputFormat(BaseModel):
    """
    输出格式
    """
    is_pass: bool = Field(..., description="是否通过")
    correction_targets: str = Field(
        default="",
        description='如果is_pass为false，明确指出需要修正的Agent名称和修正指令。例如："需要 hr Agent 补充离职流程中的资产交接步骤"；如果is_pass为true，此字段输出空字符串。'
    )


async def audit_agent(state: State, config: RunnableConfig):
    """收集子Agent返回的答案，并进行整理。消除重复或冲突，合成一段逻辑连贯、主次分明的最终回答，并统一整理所有引用来源。"""
    # 获取aggregator Agent的输出
    content = state.sub_agent_response["aggregator"]

    logger.info(f"【Audit Agent的输入】: {content['回复内容'][:10]}...")

    system_prompt = """
    # 角色定位
    你是公司政令合规的“最后把关人”。你的唯一任务是：判断“最终回复”是否基于现有知识库【真正解决了】用户的原始问题，并确保回复中没有专家凭空捏造的虚假信息。

    # 核心审核准则（仅需满足以下三点即可通过）
    1. **意图覆盖率（是否答完）**：
       - 检查用户提问中的所有子问题是否都有回应。
       - **注意**：如果知识库中确实没有相关规定，而回复诚实地说明了“未查到相关制度，建议咨询XX部门”，这属于【完美解决】。绝对不要因为知识库缺失信息而责怪回复，只要它诚实且给出了后续建议即可。
    2. **事实严谨性（是否瞎编）**：
       - **红线规则**：严禁专家在没有获取到具体正文的情况下，根据文档标题或大纲猜测具体数字（如天数、金额）、法律条文或系统操作细节。
       - 如果你发现回复中出现了检索上下文（Context）中完全没有提到的具体规定（如“10个工作日”、“第XX条”），必须判定为“幻觉”并打回。
    3. **拒绝“过度审查”**：
       - 严禁要求回复提供用户【没问过】的信息。
       - 严禁因为语气不够优美或格式问题而打回。只要逻辑通顺、事实准确、回应了用户需求，就必须予以通过。
    # 判定逻辑
    - **通过 (is_pass=True)**：回复回应了用户的所有提问点（包括诚实告知查不到的情况），且所有事实陈述在上下文中均有据可查。
    - **打回 (is_pass=False)**：
      - 存在“幻觉”：回复中出现了上下文中没有的具体数字、时限或法律条款。
      - 存在“漏答”：用户明确问了某点，但回复完全没有提及（即便说没查到也算提及，完全不提才算漏答）。
    # 修改建议撰写规范
    如果审核未通过，请在 `correction_targets` 字段中明确指出：
    - “专家 XX 涉嫌凭空捏造了关于 XXX 的具体规定，请要求其重新基于正文检索，查不到请如实说明。”
    - “用户关于 XXX 的提问被遗漏了，请调度对应专家补充。”
        """
    # 创建agent
    agent = create_agent(
        model=await qwen_model(),
        system_prompt=system_prompt,
        response_format=AuditOutputFormat,
    )

    response = await agent.ainvoke(input={"messages": [{"role": "user", "content": str(content)}]}, config=config)

    response = response['structured_response']

    logger.info(f"【Audit Agent的回复】: {response.is_pass}...")

    retry_count = state.retry_count
    max_retries = state.max_retries

    if (not response.is_pass) and (retry_count < max_retries):
        # 审核不通过
        return {
            "messages": [HumanMessage(content=f'审计反馈：\n"correction_targets": {response.correction_targets}')],
            "audit_feedback": f'审计反馈：\n"correction_targets": {response.correction_targets}',
            "retry_count": retry_count + 1
        }
    # 审核通过
    final_reply = content["回复内容"]
    return {
        "audit_feedback": None,
        "sub_agent_response": None,
        "sub_agent_input_content": None,
        "result": content,
        "messages": [HumanMessage(content=f"【最终结果】{final_reply}")]
    }
```

## File: `multi_domain_enterprise_project\agent\finance_agent.py`

```py
import logging

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from multi_domain_enterprise_project.core.sub_agent_enum import SubAgentEnum
from multi_domain_enterprise_project.core.sub_agent_output_format import SubAgentOutputFormat
from multi_domain_enterprise_project.tools.mcp_tools import finance_mcp_client
from multi_domain_enterprise_project.core.model import qwen_model
from multi_domain_enterprise_project.core.self_state import State

logger = logging.getLogger(__name__)


@tool
async def get_document(runtime: ToolRuntime):
    """获取当前用户有权限查看的内部财务文档列表及大纲。
    注意：本工具只返回文档的目录和简要说明，绝不包含具体的报销标准、数字和详细条款！
    详细条款必须通过企业知识库检索工具获取。"""
    config = runtime.config  # 获取运行时配置
    user_info = config['configurable']["user_info"]  # 获取用户信息
    # 接下来的流程
    # 根据不同用户的定位，搜索出不同的文档列表，然后return
    return {
        "提示": "以下仅为文档大纲，严禁直接使用大纲内容回答用户，必须调用检索工具查看详情！",
        "文档列表": [
            {"《差旅报销管理办法》": "涵盖国内/国际差旅的住宿、交通、餐饮补贴标准，报销审批流程，票据要求及超标申请流程。"},
            {"《费用报销细则》": "办公用品、培训费、业务招待费、通讯费等日常费用的报销范围、限额标准及附件要求。"},
            {"《固定资产管理制度》": "固定资产的定义、采购审批、入库登记、折旧计算、盘点周期及报废流程。"}
        ]
    }


async def finance_agent(state: State, config: RunnableConfig):
    """解答差旅报销规则、预算申请流程、采购 SOP 等问题。"""

    content = state.sub_agent_input_content[SubAgentEnum.FINANCE.value]  # 获取主代理传进来的问题

    # 获取子agent的历史对话消息
    try:
        messages = state.sub_agent_messages[SubAgentEnum.FINANCE.value]
    except:
        messages = []

    logger.info(f"【Finance Agent的输入】: {content[:10]}...")

    system_prompt = """
你是公司极其严谨的财务合规官。你的任务是解答员工关于报销、预算和财务制度的问题。

【核心规则】
1. 数据绝对准确：你对数字、额度限制极度敏感。绝不能捏造任何报销额度或财务规则。
2. 严格基于上下文：所有答案必须从检索内容中提取。
3. 引用机制：必须在每一条规则后加上引用来源。

【⚠️ 强制执行的工作流 (SOP) ⚠️】
你必须严格按照以下顺序执行操作，不可跳过任何一步：
第一步：调用 `get_document` 工具，获取当前可用的财务文档列表。
第二步：仔细分析用户问题，从列表中找到最匹配的文档名称（如“《差旅报销管理办法》”）。
第三步：**绝对核心** -> 你必须调用知识库检索工具，将上一步找到的文档名称作为参数传入，去检索真实的规章制度详情！
第四步：**严禁偷懒** -> 绝不能仅凭 `get_document` 返回的寥寥几句摘要就直接回答用户，你必须看到检索工具返回的详细正文后，才能开始撰写最终回答！如果检索出来的内容不足以回答用户问题时，就换种问题再次检索知识库，超过三次检索就直接回答用户
    """

    mcp_client = await finance_mcp_client()
    try:
        mcp_tools = await mcp_client.get_tools()
        agent = create_agent(
            model=await qwen_model(),
            system_prompt=system_prompt,
            tools=[get_document] + mcp_tools,
            response_format=SubAgentOutputFormat,
            middleware=[
                SummarizationMiddleware(
                    model=await qwen_model(),
                    trigger=("messages", 8),
                    keep=("messages", 4)
                )
            ]
        )
        # 组装messages
        messages.append({"role": "user", "content": content})

        response = await agent.ainvoke(input={"messages": messages}, config=config)
    finally:
        if hasattr(mcp_client, "close"):
            await mcp_client.close()
        elif hasattr(mcp_client, "aclose"):
            await mcp_client.aclose()

    messages = response['messages']
    structured_response = response['structured_response']

    logger.info(f"【Finance Agent的回复】: {structured_response.result[:10]}...")

    return {
        "sub_agent_response": {
            "【Finance Agent的回复】": {
                "回复内容": structured_response.result,
                "参考资料": structured_response.references
            },
        },
        "sub_agent_messages": {
            SubAgentEnum.FINANCE.value: messages
        }
    }
```

## File: `multi_domain_enterprise_project\agent\hr_agent.py`

```py
import logging

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import interrupt
from langchain.agents.middleware import SummarizationMiddleware

from multi_domain_enterprise_project.core.model import qwen_model
from multi_domain_enterprise_project.core.self_state import State
from multi_domain_enterprise_project.core.sub_agent_enum import SubAgentEnum
from multi_domain_enterprise_project.core.sub_agent_output_format import SubAgentOutputFormat
from multi_domain_enterprise_project.tools.mcp_tools import document_retriever_mcp_client

logger = logging.getLogger(__name__)


@tool
async def get_document(runtime: ToolRuntime):
    """获取内部文档列表"""
    config = runtime.config  # 获取运行时配置
    user_info = config['configurable']["user_info"]  # 获取用户信息

    logger.info(f"【HR Agent中】的user_info: {user_info}")

    # 接下来的流程
    # 根据不同用户的定位，搜索出不同的文档列表，然后return
    # 手动构建，用于快速测试
    return {
        "文档列表": [
            {"《员工手册》": "公司基本规章制度、员工行为规范、考勤管理、办公纪律、入职离职流程、着装要求、办公设备使用规定等。"},
            {"《休假管理制度》": "涵盖年假、病假、事假、婚假、产假、陪产假、丧假等各类假期的申请流程、审批权限、计算方式及未休处理。"},
            {"《薪酬福利指南》": "薪酬结构、薪资发放周期、绩效考核与调薪机制、奖金政策、五险一金、商业保险、餐补、交通补贴、节日福利等。"},
            {"《绩效管理办法》": "绩效评估周期、流程、考核指标设定、等级评定标准、绩效结果在晋升、奖金、改进计划中的应用。"}
        ]
    }


async def hr_agent(state: State, config: RunnableConfig):
    """专门解答员工手册、请假制度、入职流程、福利政策等问题。"""
    # 获取主代理传进来的问题
    content = state.sub_agent_input_content[SubAgentEnum.HR.value]

    # 获取子agent的历史对话消息
    try:
        messages = state.sub_agent_messages[SubAgentEnum.HR.value]
    except:
        messages = []

    logger.info(f"【HR Agent】的输入: {content[:10]}...")

    system_prompt = """
# 角色定位
你是公司资深的人力资源专家，你的任务是耐心、专业地解答员工关于 HR 政策的疑问。你可以使用工具来获取信息。你配备了多个专业的知识库工具（例如：《员工手册》、《休假管理制度》、《薪酬福利指南》、《绩效管理办法》等）。
# 任务
针对用户的提问，首先判断需要查询哪个（或哪些）文档库，然后主动调用相应的工具获取准确答案，并基于搜索结果专业、耐心地解答。
# 遵守的规则
- 选择工具：在回答问题前，先分析用户的问题涉及哪个政策领域（如休假、薪酬、考勤等），从而决定应该查询哪个文档库。如果有疑问，可以调用最相关的文档库进行搜索。
- 基于事实回答：你只能基于工具返回的搜索结果来回答问题。如果返回的内容中包含答案，请组织成清晰、专业的回答，并在回答末尾注明信息来源（如 [《休假管理制度》]）。如果返回的内容不足以回答问题，或者完全没有相关信息，请明确回答：“抱歉，根据目前的 HR 知识库，我没有找到关于该问题的规定，请联系 HRBP 获取帮助。”
- 语气与格式：保持同理心、温和且专业。对于复杂的流程，尽量使用列表或分段让步骤清晰易懂。
# 开始你的任务
    """

    mcp_client = await document_retriever_mcp_client()

    # 创建agent
    try:
        mcp_tools = await mcp_client.get_tools()
        agent = create_agent(
            model=await qwen_model(),
            system_prompt=system_prompt,
            tools=[get_document] + mcp_tools,
            response_format=SubAgentOutputFormat,
            middleware=[
                SummarizationMiddleware(
                    model=await qwen_model(),
                    trigger=("messages", 8),
                    keep=("messages", 4)
                )
            ]
        )

        # 组装messages
        messages.append(HumanMessage(content=content))

        response = await agent.ainvoke(input={"messages": messages}, config=config)
    finally:
        # 关闭服务
        if hasattr(mcp_client, "close"):
            await mcp_client.close()
        elif hasattr(mcp_client, "aclose"):
            await mcp_client.aclose()

    messages = response['messages']
    structured_response = response['structured_response']

    logger.info(f"【HR Agent】的输出: {structured_response.result[:10]}...")

    return {
        "sub_agent_response": {
            "【HR Agent的回复】": {
                "回复内容": structured_response.result,
                "参考资料": structured_response.references
            },
        },
        "sub_agent_messages": {
            SubAgentEnum.HR.value: messages
        }
    }


```

## File: `multi_domain_enterprise_project\agent\legal_agent.py`

```py
import logging

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from pydantic import Field

from multi_domain_enterprise_project.core.sub_agent_enum import SubAgentEnum
from multi_domain_enterprise_project.core.sub_agent_output_format import SubAgentOutputFormat
from multi_domain_enterprise_project.tools.mcp_tools import legal_mcp_client
from multi_domain_enterprise_project.core.model import qwen_model
from multi_domain_enterprise_project.core.self_state import State

logger = logging.getLogger(__name__)


@tool
async def get_document(runtime: ToolRuntime):
    """获取公司内部文档列表"""
    config = runtime.config  # 获取运行时配置
    user_info = config['configurable']["user_info"]  # 获取用户信息
    # 接下来的流程
    # 根据不同用户的定位，搜索出不同的文档列表，然后return
    return {
        "文档列表": [
            {
                "《保密协议模板与指引》": "涵盖公司标准保密协议（NDA）模板、签署流程、保密条款要点、违约责任说明，适用于与外部合作伙伴、客户或员工签署保密协议时参考。"},
            {
                "《数据保护与隐私政策》": "依据《个人信息保护法》（PDPA）及其他适用法规，规定个人信息收集、存储、使用、共享、删除的合规要求，以及数据泄露应急处理流程。"},
            {
                "《合同审核指南与模板库》": "包括销售合同、采购合同、劳动合同、技术开发合同等常用合同模板，及合同审核清单、风险点提示、修改建议示例。"},
            {
                "《反贿赂与反腐败政策》": "明确公司对商业贿赂、利益冲突的零容忍立场，规定礼品与招待限额、利益冲突申报流程、举报渠道及违规后果。"},
            {
                "《知识产权合规手册》": "涵盖专利、商标、著作权、商业秘密的管理与保护规则，员工在职期间及离职后的知识产权归属约定，开源代码使用规范。"}
        ]
    }


async def legal_agent(state: State, config: RunnableConfig):
    """解答保密协议（NDA）、数据保护法（PDPA）、合同模板等合规类问题。"""

    content = state.sub_agent_input_content[SubAgentEnum.LEGAL.value]

    # 获取子agent的历史对话消息
    try:
        messages = state.sub_agent_messages[SubAgentEnum.LEGAL.value]
    except:
        messages = []

    logger.info(f"【Legal Agent】的输入: {content[:10]}...")

    system_prompt = """
# 角色定位
作为公司的首席法务官兼合规专家，你配备了内部法律知识库搜索工具。
# 任务
针对用户的提问，主动判断是否需要查找相关法律政策，并自行调用“内部法律文档搜索”工具获取准确信息，然后基于搜索结果专业、严谨地解答。
# 遵守的规则
- 主动检索：在回答前，分析用户的问题涉及哪个法务领域（如合同条款、数据保护、保密协议等）。如果问题需要查询具体规定，必须调用工具，构造合适的搜索查询来获取最新、最准确的内部法律文档内容。
- 极度保守：法律无小事。你的回答必须极其精准，仅基于工具返回的【检索内容】，原文怎么规定的，你就怎么解释，不可自行引申或做过度宽泛的解读。
- 忠于上下文：只依赖工具返回的【检索内容】。如果返回的内容不足以回答问题，或者完全没有相关信息，请明确回答：“抱歉，根据内部法律知识库，我未能找到关于该问题的具体规定。建议你提交流程由法务部人工复核。”
- 严格引用：精准引用相关的法务条款或文档名称，在回答中标注来源（如 [《数据保护政策》第3.2条]）。
- 免责声明：在每次回答的末尾，必须强制加上这句话：```免责声明：以上回答基于公司内部知识库生成，仅供参考，不作为最终的法律意见。如遇重大法务决策，请务必提交流程由法务部人工复核。```
    """

    mcp_client = await legal_mcp_client()

    # 创建agent
    try:
        mcp_tools = await mcp_client.get_tools()
        agent = create_agent(
            model=await qwen_model(),
            system_prompt=system_prompt,
            tools=[get_document] + mcp_tools,
            response_format=SubAgentOutputFormat,
            middleware=[
                SummarizationMiddleware(
                    model=await qwen_model(),
                    trigger=("messages", 8),
                    keep=("messages", 4)
                )
            ]
        )
        # 组装messages
        messages.append({"role": "user", "content": content})

        response = await agent.ainvoke(input={"messages": messages}, config=config)
    finally:
        # 关闭服务
        if hasattr(mcp_client, "close"):
            await mcp_client.close()
        elif hasattr(mcp_client, "aclose"):
            await mcp_client.aclose()

    messages = response['messages']
    structured_response = response['structured_response']

    logger.info(f"【Legal Agent】的回复: {structured_response.result[:10]}...")

    return {
        "sub_agent_response": {
            "【Legal Agent的回复】": {
                "回复内容": structured_response.result,
                "参考资料": structured_response.references
            },
        },
        "sub_agent_messages": {
            SubAgentEnum.LEGAL.value: messages
        }
    }
```

## File: `multi_domain_enterprise_project\agent\supervisor_agent.py`

```py
from typing import Annotated, Union, List, Dict
import logging

from langchain_core.messages import ToolMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.constants import END
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode, tools_condition, ToolRuntime
from langgraph.types import Checkpointer, Command, interrupt
from pydantic import Field

from multi_domain_enterprise_project.agent.tech_agent import tech_agent_node
from multi_domain_enterprise_project.agent.aggregator_agent import aggregator_agent
from multi_domain_enterprise_project.agent.audit_agent import audit_agent
from multi_domain_enterprise_project.agent.finance_agent import finance_agent
from multi_domain_enterprise_project.agent.hr_agent import hr_agent
from multi_domain_enterprise_project.agent.legal_agent import legal_agent
from multi_domain_enterprise_project.core.model import qwen_model
from multi_domain_enterprise_project.core.self_state import State
from multi_domain_enterprise_project.core.sub_agent_enum import SubAgentEnum

logger = logging.getLogger(__name__)


@tool
async def get_sub_agent_list() -> List[Dict]:
    """获取当前系统中所有可用的子代理专家列表及其能力描述。

    当你需要了解可用的专业子代理及其负责领域时，调用此工具。返回的列表中每个元素包含：
    - sub_agent_name: 子代理标识符（用于后续 invoke_sub_agent 工具调用）
    - description: 子代理的职责和能力说明
    在路由决策不确定时，可先调用此工具获取完整列表，以帮助判断将用户问题分发给哪个子代理。"""
    logger.info(f"【get_sub_agent_list】")
    return [
        {"sub_agent_name": i.value, "description": i.description} for i in SubAgentEnum
    ]


@tool
async def invoke_sub_agent(sub_agent_name: Annotated[str, Field(..., description="子代理名称")],
                           content: Annotated[str, Field(...,
                                                         description="给专家下达的具体任务指令。警告：必须是陈述句指令，严禁在此处填写对用户意图的疑问！")],
                           runtime: ToolRuntime) -> Union[str, Command]:
    """向专家下发任务。如果用户问题涉及多个领域，可以被并发调用多次。"""
    try:
        operation = SubAgentEnum(sub_agent_name)
    except:
        return f"子代理 {sub_agent_name} 不存在,仔细检查子代理名称"
    logger.info(f"调用 {operation.value} 代理成功!")
    tool_call_id = runtime.tool_call_id
    return Command(
        goto=operation.value,
        update={
            "sub_agent_input_content": {operation.value: content},
            "messages": [
                ToolMessage(
                    content=f"调用 {operation.value} 代理成功! 等待审核结果",
                    name='invoke_sub_agent',
                    tool_call_id=tool_call_id
                )
            ]
        }
    )


@tool
async def human_in_loop(content: Annotated[str, Field(..., description="发送给用户的内容")], runtime: ToolRuntime):
    """当用户问题模糊或置信度低时，使用此工具向用户提问以获取更多信息。"""
    if not content:
        return "输入的内容为空"
    decision = interrupt({
        "action": "human_decision",
        "content": content
    })
    if not decision:
        return "用户没有输入内容"
    return {"用户的回复": decision['content']}


async def create_graph(checkpointer: Checkpointer):
    # 定义工具列表
    tools = [get_sub_agent_list, invoke_sub_agent, human_in_loop]
    # 获取模型
    model = await qwen_model('qwen-max')
    # 定义工具节点
    too_node = ToolNode(tools)
    # 定义系统提示词
    system_prompt = """
    # 角色定位
    你是多代理系统的“交通枢纽”，负责接收用户问题，并将其路由给合适的领域专家Agent。**你不需要直接回答用户，只负责“分发任务”或“向用户追问”。**

    ## 模式识别
    根据当前对话状态，你会有两种工作模式：

    ### 模式一：首次路由
    当 **没有审计反馈（state 中 audit_feedback 为空）** 时，你处于首次路由模式：
    - 💡 **超级能力与严厉警告**：
      1. 你具备**并发调度**能力！如果用户的问题同时包含多个领域的意图，你**必须在一次回答中，并发生成多个 invoke_sub_agent 调用**！
      2. **严禁分批或分步处理！** 不允许先发两个任务等结果再发剩下的！必须一次性穷尽提取用户的所有意图并全部分发！
      3. **严禁工具混用**：绝不能在同一次回答中既调用 invoke_sub_agent 又调用 human_in_loop。

    - **工作流程**：
      1. 深挖用户意图，拆解出所有包含的专业领域。
      2. 执行动作：
         - 领域明确（置信度 ≥ 0.7）：并发调用多次 `invoke_sub_agent`，将拆解后的所有子任务一次性全部下发！
         - 信息模糊（置信度 < 0.7）：调用 `human_in_loop`，直接向用户提问澄清。

    ### 模式二：修正路由
    - ⚡️ 严厉警告：当你接收到审计反馈时，你【必须且只能】使用 `invoke_sub_agent` 工具重新下发修正指令！
    - 绝不允许使用自然语言进行回复或安抚（如“好的”、“已转交”、“马上处理”等废话）。只要你不输出工具调用，整个系统就会崩溃退出！
    - 审计反馈格式：
        "correction_targets": {
          "hr": "请补充离职流程中的资产交接步骤",
          "legal": "确保引用正确的法律条文，不要捏造"
        }
    """

    # model绑定系统提示词和工具
    agent = model.bind_tools(tools=tools)  # 绑定工具

    async def supervisor_agent(state: State, config: RunnableConfig):
        """它是整个多代理系统的“大脑”和“交通枢纽”，直接面向用户输入。"""
        sys_prompt = SystemMessage(content=system_prompt)

        messages = [sys_prompt] + state.messages

        logger.info(f"【supervisor_agent】开始执行: {state.messages[-1]}")
        response = []
        try:
            response = await agent.ainvoke(messages, config=config)
        except:
            logger.error(f"【supervisor_agent】执行错误")

        return {"messages": [response]}

    async def audit_router(state: State, config: RunnableConfig):
        """用于审核子代理的输出，并给出相应的反馈。"""
        audit_feedback = state.audit_feedback
        if not audit_feedback:
            return END
        logger.info(f"【audit_router】返回审核：{state.messages[-1].content[:10]}")
        return "supervisor"

    graph = StateGraph(State)

    graph.add_node("supervisor", supervisor_agent)
    graph.add_node("tools", too_node)
    graph.add_node("tech", tech_agent_node)
    graph.add_node("hr", hr_agent)
    graph.add_node("finance", finance_agent)
    graph.add_node("legal", legal_agent)
    graph.add_node("aggregator", aggregator_agent)
    graph.add_node("audit", audit_agent)

    graph.set_entry_point("supervisor")
    graph.add_conditional_edges(
        "supervisor",
        path=tools_condition
    )
    graph.add_edge("tools", "supervisor")
    graph.add_edge("tech", "aggregator")
    graph.add_edge("hr", "aggregator")
    graph.add_edge("finance", "aggregator")
    graph.add_edge("legal", "aggregator")

    graph.add_edge("aggregator", "audit")

    graph.add_conditional_edges(
        "audit",
        path=audit_router
    )

    return graph.compile(checkpointer=checkpointer)
```

## File: `multi_domain_enterprise_project\agent\tech_agent.py`

```py
import logging

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from pydantic import Field

from multi_domain_enterprise_project.core.sub_agent_enum import SubAgentEnum
from multi_domain_enterprise_project.core.sub_agent_output_format import SubAgentOutputFormat
from multi_domain_enterprise_project.tools.mcp_tools import tech_mcp_client
from multi_domain_enterprise_project.core.model import qwen_model
from multi_domain_enterprise_project.core.self_state import State

logger = logging.getLogger(__name__)


@tool
async def get_document(runtime: ToolRuntime):
    """获取内部文档列表"""
    config = runtime.config  # 获取运行时配置
    user_info = config['configurable']["user_info"]  # 获取用户信息
    # 接下来的流程
    # 根据不同用户的定位，搜索出不同的文档列表，然后return
    return {
        "文档列表": [
            {
                "《API开发规范与接口文档》": "公司内部 API 的设计规范、命名规则、认证方式、版本管理，以及各核心服务（用户服务、订单服务、支付服务等）的接口说明、请求响应示例。"},
            {
                "《系统架构设计文档》": "微服务架构概览、服务间通信协议（REST/gRPC/消息队列）、数据流图、关键技术栈说明（如 Spring Cloud、Kubernetes）、高可用与容灾设计。"},
            {
                "《代码规范与最佳实践》": "后端（Java/Python）编码规范、前端（React/Vue）代码风格、Git 提交规范、Code Review 流程、单元测试覆盖率要求。"},
            {"《数据库设计文档》": "各业务数据库的表结构、字段含义、索引策略、分库分表规则、数据迁移与备份方案。"}
        ]
    }


async def tech_agent_node(state: State, config: RunnableConfig):
    """负责解答 API 文档、内部系统架构、代码规范、项目 Wiki 等问题。"""

    content = state.sub_agent_input_content[SubAgentEnum.TECH.value]  # 获取主代理传进来的问题
    # 获取子agent的历史对话消息
    try:
        messages = state.sub_agent_messages[SubAgentEnum.TECH.value]
    except:
        messages = []
    logger.info(f"【Tech Agent】的输入：{content[:10]}...")

    system_prompt = """
# 角色定位
作为公司的高级技术专家兼IT支持主管，你配备了多种查询工具（例如“内部技术文档搜索”和“网络搜索”）。
# 任务
针对用户的提问，主动判断是否需要查找信息，并自行调用合适的工具获取准确答案，然后基于搜索结果专业、清晰地解答。
# 遵守的规则
- 主动检索：在回答前，先分析问题涉及的范围。
  - 如果问题涉及公司内部系统、API、特定项目或内部技术细节，必须调用“内部技术文档搜索”工具。
  - 如果问题涉及通用技术概念、外部库、行业标准或需要最新信息，可以调用“网络搜索”工具。
  - 如果问题简单且你确信无需查询（例如常见编程语法），可以直接回答，但必须确保准确。
- 基于事实回答：你只能基于工具返回的信息来回答问题。如果返回的内容包含答案，请组织成清晰、专业的回答，并遵守以下格式要求：
  - 代码与技术细节：严格保留原始代码结构，使用 Markdown 代码块并标明语言（如 python,json）。
  - 逻辑清晰：解释系统架构或排障步骤时，使用有序列表（Step 1, Step 2...）。
  - 引用来源：在回答末尾标注信息来源（如 [内部文档: API指南] 或 [网络来源: MDN Web Docs]）。
- 知识边界：如果工具返回的信息不足以回答问题，或完全没有相关信息，请明确回答：“抱歉，根据现有资料无法找到该问题的确切答案，建议联系相关团队或查阅最新文档。” 绝不允许猜测未提供的参数或虚构信息。
    """

    mcp_client = await tech_mcp_client()

    # 创建agent
    try:
        mcp_tools = await mcp_client.get_tools()
        agent = create_agent(
            model=await qwen_model(),
            system_prompt=system_prompt,
            tools=[get_document] + mcp_tools,
            response_format=SubAgentOutputFormat,
            middleware=[
                SummarizationMiddleware(
                    model=await qwen_model(),
                    trigger=("messages", 8),
                    keep=("messages", 4)
                )
            ]
        )
        # 组装messages
        messages.append({"role": "user", "content": content})

        response = await agent.ainvoke(input={"messages": messages}, config=config)
    finally:
        # 关闭服务
        if hasattr(mcp_client, "close"):
            await mcp_client.close()
        elif hasattr(mcp_client, "aclose"):
            await mcp_client.aclose()

    messages = response['messages']
    structured_response = response['structured_response']

    logger.info(f"【Tech Agent】最终回复：{structured_response.result.result[:10]}...")

    return {
        "sub_agent_response": {
            "【Tech Agent的回复】": {
                "回复内容": structured_response.result,
                "参考资料": structured_response.references
            },
        },
        "sub_agent_messages": {
            SubAgentEnum.TECH.value: messages
        }
    }
```

## File: `multi_domain_enterprise_project\agent\__init__.py`

```py

```

## File: `multi_domain_enterprise_project\core\model.py`

```py
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from config import settings


async def qwen_model(model: str = 'qwen-plus') -> BaseChatModel:
    """获取qwen实例"""
    model = ChatOpenAI(
        model=model,
        api_key=settings.llm_key.qwen,
        base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
    )
    return model
```

## File: `multi_domain_enterprise_project\core\self_state.py`

```py
from typing import Optional, Dict, List, Annotated, Any

from langchain_core.messages import BaseMessage
from langgraph.graph import MessagesState, add_messages
from pydantic import BaseModel


def merge_dict(old_tasks: Dict[str, Any], new_tasks: Dict[str, Any]) -> Dict[str, Any]:
    """字典合并函数"""
    if old_tasks is None:
        old_tasks = {}
    if new_tasks is None:
        return {}
    merged = old_tasks.copy()
    merged.update(new_tasks)
    return merged


def replace_dict(old_tasks: Dict[str, Any], new_tasks: Dict[str, Any]) -> Dict[str, Any]:
    """替代字典"""
    if new_tasks is None:
        return {}
    return new_tasks


class State(BaseModel):
    messages: Annotated[list[BaseMessage], add_messages]
    sub_agent_input_content: Annotated[Dict[str, Any], merge_dict]  # 给子Agent的输入
    sub_agent_messages: Annotated[Dict[str, list], replace_dict]  # 子Agent的messages消息
    sub_agent_response: Annotated[Dict[str, Any], merge_dict]  # 子Agent的输出
    audit_feedback: Optional[Any] = None  # 审计反馈
    result: Optional[Any] = None
    retry_count: int = 0  # 当前重试次数
    max_retries: int = 3  # 最大重试次数
```

## File: `multi_domain_enterprise_project\core\sub_agent_enum.py`

```py
from enum import Enum


class SubAgentEnum(Enum):
    FINANCE = ("finance", "财务代理: 解答差旅报销规则、预算申请流程、采购 SOP 等问题。")
    TECH = ("tech", "技术代理： 负责解答 API 文档、内部系统架构、代码规范、项目Wiki等问题。")
    LEGAL = ('legal', "法律代理： 解答保密协议、数据保护法、合同模板等企业内合规问题。")
    HR = ('hr', "HR代理: 专门解答员工手册、请假制度、入职流程、福利政策等问题。")

    def __new__(cls, code, description):
        obj = object.__new__(cls)
        obj._value_ = code          # 将值设为 code
        obj.description = description  # 附加描述
        return obj


if __name__ == '__main__':
    try:
        o = SubAgentEnum("hr")
    except:
        print("不存在")

    print(SubAgentEnum.HR.value)
    print(SubAgentEnum.HR.description)
    print([i for i in SubAgentEnum])
```

## File: `multi_domain_enterprise_project\core\sub_agent_output_format.py`

```py
from typing import Annotated, Any

from pydantic import BaseModel, Field


class SubAgentOutputFormat(BaseModel):
    result: Annotated[str, Field(...,description="最后的回复")]
    references: Annotated[list[Any], Field(..., description="""列出所有通过文档检索到的上下文，例如：['xxx', 'xxxxx']""")]
```

## File: `multi_domain_enterprise_project\core\__init__.py`

```py

```

## File: `multi_domain_enterprise_project\mcp_server\run_mcp.py`

```py
import asyncio
import logging

from multi_domain_enterprise_project.mcp_server.server_mcp_tools import build_mcp_server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    logger.info("🔄 正在初始化企业知识库 MCP 服务...")
    mcp_app = await build_mcp_server()

    logger.info("🚀 服务已启动！监听 8000 端口 (streamable-http Transport)")

    await mcp_app.run_async(
        transport="streamable-http",
        host="127.0.0.1", port=8000,
        show_banner=True,
        log_level='debug',
        path='/rag-retriever'
    )


if __name__ == "__main__":
    asyncio.run(main())
```

## File: `multi_domain_enterprise_project\mcp_server\server_mcp_tools.py`

```py
import asyncio
from typing import Annotated, Literal

from fastmcp import FastMCP, Context
from fastmcp.server.auth.providers.jwt import RSAKeyPair, JWTVerifier
from pydantic import SecretStr, Field
import logging
import aiofiles

from multi_domain_enterprise_project.rag.rag_main import query_milvus_pipeline, get_all_documents_name
from multi_domain_enterprise_project.rag.rag_service import retrieve_service

logger = logging.getLogger(__name__)


async def get_public_key():
    async with aiofiles.open("./public_key", "r") as f:
        return await f.read()


async def get_private_key():
    async with aiofiles.open("./private_key", "r") as f:
        return await f.read()


async def get_auth():
    # 配置认证提供方
    auth = JWTVerifier(
        public_key=await get_public_key(),  # 公钥用于校验签名
        issuer='https://xinyu.com',  # 令牌签发方标识
        audience='my-dev-server',  # 令牌接收方标识
    )
    return auth


async def build_mcp_server() -> FastMCP:
    """
    MCP 注册中心工厂函数。
    在这里集中注册所有的业务函数，将其暴露为 MCP Tools。
    """
    mcp = FastMCP("企业知识库检索服务", instructions="提供混合检索能力，并支持按元数据过滤的知识库。",
                  auth=await get_auth())

    # 注册 RAG 工具
    @mcp.tool()
    async def query_document(query_str: Annotated[str, Field(..., description="检索的内容（必须提供）")], ctx: Context,
                             title: Annotated[str, Field(..., description="可选，指定文档标题（精确匹配）。")] = None,
                             mode: Annotated[Literal['milvus', 'graph', 'mg'],
                             Field(...,
                                   description="默认是 'milvus'。"
                                               "'milvus' 表示检索向量数据库；"
                                               "'graph' 表示检索知识图谱; "
                                               "'mg': 表示检索向量数据库+知识图谱;")] = 'milvus'
                             ) -> str:
        """
        在企业知识库中检索信息。
        """
        # tenant_id: 租户id  部门
        # acl: 访问控制列表（通过用户的职别控制）

        # 1. 从 MCP Context 中获取经过验证的 Token 信息
        # 注：根据 FastMCP 版本不同，auth 的获取路径可能略有差异，通常在 ctx.request 或者直接封装在 ctx 中
        # 如果 JWTVerifier 验证成功，它会将解析后的 subject 存入上下文
        try:
            # 获取签发时填入的 subject
            claims = ctx.request_context.request.user.access_token.claims  # 假设 subject 为 "hr|1,2"
            logger.warning(f"ctx.request_context.request.user.access_token.claims: {claims}")
            tenant_id = claims.get("tenant", None)
            acl_str = claims.get("acl", None)
            if (not tenant_id) or (not acl_str):
                return "检索失败：系统无法识别您的租户身份权限。"
            acl_list = acl_str.split("|") if acl_str else []
        except Exception as e:
            logger.error(f"认证失败：{e}")
            return "检索失败：系统无法识别您的租户身份权限。"

        logger.info(f"拦截到合法请求 -> Tenant: {tenant_id}, ACL: {acl_list}, Query: {query_str}")

        try:
            # 将参数发往底层 Pipeline
            return await retrieve_service(
                query_str=query_str,
                title=title,
                tenant_id=tenant_id,
                acl_list=acl_list,
                mode=mode
            )
        except:
            return "服务器内部错误"

    # @mcp.tool()
    # async def get_documents_list():
    #     """
    #     获取企业内容的所有文档名称和简要概述
    #     :return:
    #     """
    #     return await get_all_documents_name("hr", "1")

    # 可以在这里继续注册其他工具...
    # @mcp.tool()
    # async def other_tool(...): pass

    return mcp


async def create_mcp_token(tenant: str, acl: str):
    """
    注册令牌
    acl: 1|2|3
    """

    key_pair = RSAKeyPair(private_key=SecretStr(await get_private_key()), public_key=await get_public_key())

    subject_payload = f"{tenant}|{acl}"

    return key_pair.create_token(
        subject=subject_payload,  # 用户唯一标识符
        issuer='https://xinyu.com',  # 令牌签发方标识
        audience='my-dev-server',  # 令牌接收方标识
        expires_in_seconds=3600 * 24 * 7,  # 令牌有效期
        additional_claims={"tenant": tenant, "acl": acl}
    )


if __name__ == '__main__':
    res = asyncio.run(create_mcp_token("hr", '1|2'))
    print(res)
```

## File: `multi_domain_enterprise_project\mcp_server\__init__.py`

```py

```

## File: `multi_domain_enterprise_project\rag\chunker.py`

```py
import logging
from typing import List, Dict, Any
from llama_index.core.schema import Document, BaseNode
from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("EnterpriseChunker")


class EnterpriseDocumentChunker:
    """
    企业级级联切片器
    适配了 Router 输出的 Markdown 字符串，自动包装并执行级联切片。
    """

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # 第一把刀：Markdown 结构切片器
        self.md_parser = MarkdownNodeParser()

        # 第二把刀：递归句子切片器 (长度控制器)
        self.text_parser = SentenceSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap
        )

    def split_text(self, markdown_text: str, metadata: Dict[str, Any] = None) -> List[BaseNode]:
        """
        核心方法：接收 Markdown 字符串进行切片
        :param markdown_text: Router 返回的 markdown 文本
        :param metadata: 文件的元数据（如 {"source_file": "合同.pdf"}），用于后续溯源
        """
        if not markdown_text or not markdown_text.strip():
            logger.warning("⚠️ 输入的文本为空，跳过切片。")
            return []

        metadata = metadata or {}

        doc = Document(
            text=markdown_text,
            metadata=metadata
        )

        # 设置元数据不参与 Embedding 计算（防止文件名污染语义空间） 但在检索出结果后，展示给用户时依然可见
        doc.excluded_embed_metadata_keys = list(metadata.keys())

        logger.info(f"🔪 启动级联切片，输入文本长度: {len(markdown_text)} 字符")

        # 1. 第一刀：按 Markdown 结构 (##, ###) 智能切分
        structural_nodes = self.md_parser.get_nodes_from_documents([doc])
        logger.info(f"   ✂️ [结构切片] 生成粗粒度节点: {len(structural_nodes)} 个")

        # 2. 第二刀：对超过 chunk_size 的长文本块，在标点符号处安全截断
        final_nodes = self.text_parser.get_nodes_from_documents(structural_nodes)
        logger.info(f"   ✂️[长度切片] 生成最终安全节点: {len(final_nodes)} 个")

        # 确保幂等性，避免重复向量化
        for node in final_nodes:
            node.id_ = node.hash  # LlamaIndex 自动基于 content 和 metadata 计算的 hash

        return final_nodes




```

## File: `multi_domain_enterprise_project\rag\document_in_database.py`

```py
import asyncio
import os
import logging
import re
import time
from pathlib import Path

from multi_domain_enterprise_project.rag.documentParser.parser_route import DocumentParserRouter
from multi_domain_enterprise_project.rag.chunker import EnterpriseDocumentChunker
from multi_domain_enterprise_project.rag.graph.ingestion_graph import GraphStorePipelineService
from multi_domain_enterprise_project.rag.milvus.ingestion_milvus import MilvusStorePipelineService

import short_unique_id as suid

logger = logging.getLogger(__name__)


async def get_snowflake_id() -> str:
    """
    生成一个随机的 snowflake ID
    """
    return str(suid.get_next_snowflake_id())


async def _clean_markdown_wrapper(text: str) -> str:
    """
    清洗解析器可能附带的 ```markdown ... ``` 外套
    """
    text = text.strip()
    # 使用正则匹配，兼容 ```markdown, ```md, 或者仅有 ``` 开头的情况
    # re.DOTALL 使得 . 可以匹配换行符
    pattern = r"^```(?:markdown|md)?\s*\n(.*?)\n```$"
    match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)

    if match:
        logger.info("🧹 检测到 ```markdown 外套，已自动剥离！")
        return match.group(1).strip()

    # 兜底：如果没匹配上正则，但确实以 ``` 开头和结尾（比如没有换行的情况）
    if text.startswith("```") and text.endswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("markdown"):
            text = text[8:].strip()
        elif text.lower().startswith("md"):
            text = text[2:].strip()
        logger.info("🧹 执行了基础的 markdown 外套剥离！")
        return text

    return text


async def clean_document_str(file_path: str, tenant_id: str):
    """
    获取文档的md格式文本
    :param file_path: 文档的存储路径
    :param tenant_id: 文档所属的租户
    :return:
    """
    file_name = os.path.basename(file_path)
    logger.info(f"\n⚡ [Start] 开始处理文件: {file_name}")
    router = DocumentParserRouter(mode="auto")
    try:
        # 获取md文本
        markdown_text = await router.route_and_parse(file_path)
        # 格式化md文本
        markdown_text = await _clean_markdown_wrapper(markdown_text)
        # 存储md文本
        file_path_md = Path(f"./data/{tenant_id}/{await get_snowflake_id()}.md")
        file_path_md.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path_md, 'w', encoding='utf-8') as f:
            f.write(markdown_text)
        return markdown_text, file_path_md
    except Exception as e:
        logger.error(f"❌ 解析阶段失败: {e}")
        return None, None


async def insert_document(metadata: dict, mode: str = "milvus"):
    """
    RAG ETL 主流程：文件 -> 解析 -> 切片 -> 向量化 -> 存储
    file_path: 文件存储路径
    tenant_id: 租户id  部门
    user_id: 用户id  用户账号
    title: 文档标题
    acl: 最低访问权限
    mode: 默认是 'milvus' 表示检索向量数据库；'graph' 表示检索知识图谱; 'mg': 表示检索向量数据库+知识图谱;
    """
    file_name = metadata["file_name"]

    # --- Step 1: 智能路由解析 获取文档的md格式---
    markdown_text, file_path_md = await clean_document_str(metadata["file_path"], metadata["tenant_id"])
    metadata["file_path_md"] = file_path_md

    # --- Step 2: 级联切片 ---
    chunker = EnterpriseDocumentChunker(chunk_size=512, chunk_overlap=50)
    nodes = chunker.split_text(markdown_text, metadata=metadata)

    if not nodes:
        logger.warning("⚠️ 切片结果为空，流程终止。")
        return
    logger.info(f"✅ 切片完成: {len(nodes)} 个节点")

    # --- Step 3: 向量化与存储 (Milvus/graph neo4j) ---
    if mode == "milvus":
        milvus_ingestion = MilvusStorePipelineService()
        logger.info(f"🚀 开始对 {file_name} 执行入库 (Milvus向量库 )...")
        await milvus_ingestion.insert_nodes(nodes)  # 插入数据
        logger.info(f"🎉 [Success] 文件 {file_name} 处理完毕，数据已入库！")
    elif mode == "graph":
        logger.info(f"🚀 开始对 {file_name} 执行并发入库 (Neo4j 图数据库)...")
        graph_ingestion = GraphStorePipelineService()
        await graph_ingestion.insert_nodes(nodes)
        logger.info(f"🎉 [Success] 文件 {file_name} 处理完毕，数据已入库！")
    else:
        logger.info(f"🚀 开始对 {file_name} 执行双路并发入库 (Milvus 向量库 & Neo4j 图数据库)...")
        # 如果是图文双路入库模式
        milvus_ingestion = MilvusStorePipelineService()
        graph_ingestion = GraphStorePipelineService()
        try:
            # 使用 asyncio.gather 并发执行，return_exceptions=True 保证一个失败不影响另一个
            results = await asyncio.gather(
                milvus_ingestion.insert_nodes(nodes),
                graph_ingestion.insert_nodes(nodes),
                return_exceptions=True
            )
            # 遍历检查并发任务中是否有异常抛出
            has_error = False
            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    has_error = True
                    failed_service = "Milvus 入库" if i == 0 else "Neo4j 图谱入库"
                    logger.error(f"❌ {failed_service} 发生异常: {res}")
            if not has_error:
                logger.info(f"🎉 [Success] 文件 {file_name} 处理完毕，Milvus 与 Neo4j 双路入库均成功！")
            else:
                logger.warning(f"⚠️ 文件 {file_name} 入库完成，但部分服务存在异常，请检查上方日志。")

        except Exception as e:
            logger.error(f"❌ 双路入库调度阶段发生致命错误: {e}")
```

## File: `multi_domain_enterprise_project\rag\ollama_embedding.py`

```py
from config import settings
from ollama import Client, AsyncClient
from langchain_core.embeddings import Embeddings
from typing import List

# 异步客户端，用于 aembed_* 方法
ollama_async_client = AsyncClient()
# 同步客户端，用于 embed_* 方法
ollama_sync_client = Client()


class OllamaEmbeddings(Embeddings):
    """
    一个使用Ollama本地模型并兼容LangChain的自定义Embedding类。
    """
    model_name: str = 'qwen3-embedding:4b'

    async def aembed_documents(self, texts: List[str], dims: int = settings.milvus.dims) -> List[List[float]]:
        """异步地为一组文档生成向量"""
        # 使用异步客户端
        response = await ollama_async_client.embed(
            model=self.model_name,
            input=texts,
            dimensions=dims
        )
        return response['embeddings']

    async def aembed_query(self, text: str, dims: int = settings.milvus.dims) -> List[float]:
        """异步地为单个查询文本生成向量"""
        # 使用异步客户端
        response = await ollama_async_client.embed(
            model=self.model_name,
            input=text,
            dimensions=dims
        )
        return response['embeddings'][0]

    def embed_documents(self, texts: List[str], dims: int = settings.milvus.dims) -> List[List[float]]:
        """同步地为一组文档生成向量"""
        response = ollama_sync_client.embed(
            model=self.model_name,
            input=texts,
            dimensions=dims
        )
        return response['embeddings']

    def embed_query(self, text: str, dims: int = settings.milvus.dims) -> List[float]:
        """同步地为单个查询文本生成向量"""
        response = ollama_sync_client.embed(
            model=self.model_name,
            input=text,
            dimensions=dims
        )
        return response['embeddings'][0]


ollama_embedding_function = OllamaEmbeddings()
```

## File: `multi_domain_enterprise_project\rag\rag_main.py`

```py
import asyncio
import os

import logging

from multi_domain_enterprise_project.rag.document_in_database import insert_document
from multi_domain_enterprise_project.rag.milvus.ingestion_milvus import MilvusRetrieverService

logger = logging.getLogger(__name__)


async def query_milvus_pipeline(query_str: str, filters_dict: dict = None):
    """
     在企业知识库中检索信息。
    Args:
        query_str: 用户的问题或检索语句。
        file_name: 可选，指定文件名（精确匹配）。
        title: 可选，指定文档标题（精确匹配）。
        # 通过上下文注入
        tenant_id: 租户id  部门
        acl: 访问控制列表（通过用户的职别控制）

    Returns:
        检索到的文档片段，用空行分隔。
    """

    ingestion = MilvusRetrieverService()
    query = await ingestion.retrieve_answer(query_str, filters_dict)
    if not query:
        return "检索的结果为空"
    result = "\n\n".join([i.node.get_content() for i in query])
    return result


async def upload_file_to_milvus_pipeline(file_path: str, tenant_id: str, user_id: str, title: str, acl: str,
                                         mode: str = "milvus"):
    """
    RAG ETL 主流程：文件 -> 解析 -> 切片 -> 向量化 -> 存储
    file_path: 文件存储路径
    tenant_id: 租户id  部门
    user_id: 用户id  用户账号
    title: 文档标题
    acl: 访问控制列表（通过用户的职别控制）
    mode: 默认是 'milvus' 表示只入向量数据库；'graph' 表示入向量数据库+构建知识图谱
    """
    return await insert_document(file_path, tenant_id, user_id, title, acl, mode)


async def get_all_documents_name(tenant_id: str, acl: str):
    """
    获取所有文档的名称
    """
    logger.info(f"获取所有文档的名称, tenant: {tenant_id}, 权限: {acl}")
    return {
        "": ""
    }


if __name__ == "__main__":
    # 测试文件
    test_files = [
        # r"D:\学习笔记\langchain\rag_upper\document\7181-attention-is-all-you-need.pdf",
        # r"D:\学习笔记\langchain\rag_upper\document\小论文内容整理.docx",
        # r"D:\学习笔记\langchain\rag_upper\document\transformer.png",
        r"D:\学习笔记\langchain\rag_upper\document\rag中处理excel表格.txt"
    ]

    for f in test_files:
        if os.path.exists(f):
            res = asyncio.run(upload_file_to_milvus_pipeline(f, "hr", "admin", "nzqa_institutions_full", "1", "graph"))
            # asyncio.run(query_milvus_pipeline('如何读取excel', {"acl": ["1", "2"], "tenant_id": "hr"}))
        else:
            print(f"文件不存在: {f}")
```

## File: `multi_domain_enterprise_project\rag\rag_service.py`

```py
import os
import time

from multi_domain_enterprise_project.rag.document_in_database import insert_document
from multi_domain_enterprise_project.rag.graph.ingestion_graph import GraphRetrieverService
from multi_domain_enterprise_project.rag.milvus.ingestion_milvus import MilvusRetrieverService


async def retrieve_service(query_str: str, title: str = None, tenant_id: str = None, acl_list: list = None,
                           mode: str = "milvus") -> str:
    """
    知识库检索服务
    :param query_str: 检索内容
    :param tenant_id: 租户id
    :param title: 文档标题
    :param acl_list: 可访问权限
    :param mode: 默认是 'milvus' 表示检索向量数据库；'graph' 表示检索知识图谱; 'mg': 表示检索向量数据库+知识图谱;
    :return:
    """
    # 构建过滤metadata
    filters = {
        "title": title,
        "tenant_id": tenant_id,
        "acl": acl_list,
    }

    if not query_str:
        return "请输入检索内容"
    if mode == "milvus":
        ingestion = MilvusRetrieverService()
        query = await ingestion.retrieve_answer(query_str, filters)
    elif mode == "graph":
        ingestion = GraphRetrieverService()
        query = await ingestion.retrieve_answer(query_str, filters)
    else:
        # 检索向量数据库和知识图谱
        ingestion_milvus = MilvusRetrieverService()
        query_milvus = await ingestion_milvus.retrieve_answer(query_str, filters)

        ingestion_graph = GraphRetrieverService()
        query_graph = await ingestion_graph.retrieve_answer(query_str, filters)

        query = query_milvus + query_graph

    if not query:
        return "检索的结果为空"
    return query


async def insert_service(file_path: str, tenant_id: str, user_id: str, title: str, acl: str,
                         mode: str = "milvus") -> None:
    """
    文档传入知识库服务
    :param file_path: 文档路径
    :param tenant_id: 租户id
    :param user_id: 用户id
    :param title: 文档标题
    :param acl: 可访问权限
    :param mode: 默认是 'milvus' 表示检索向量数据库；'graph' 表示检索知识图谱; 'mg': 表示检索向量数据库+知识图谱;
    :return:
    """
    # 构建元数据
    file_name = os.path.basename(file_path)  # 文件名
    metadata = {
        "file_name": str(file_name),
        "file_path": str(file_path),

        "tenant_id": str(tenant_id),
        "owner_id": str(user_id),

        "title": str(title),  # 文档标题

        "acl": str(acl),  # 最低访问权限

        "upload_time": str(time.strftime("%Y-%m-%d %H:%M:%S")),
    }
    return await insert_document(metadata, mode)
```

## File: `multi_domain_enterprise_project\rag\__init__.py`

```py

```

## File: `multi_domain_enterprise_project\rag\documentParser\exception_handling.py`

```py
class DocumentParsingError(Exception):
    """文档解析错误"""
    pass
```

## File: `multi_domain_enterprise_project\rag\documentParser\llamaparser.py`

```py
import os
import time
from pathlib import Path

import nest_asyncio
import logging

from llama_parse import LlamaParse
from llama_index.core.schema import Document
from config import settings
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from docx2pdf import convert

from multi_domain_enterprise_project.rag.documentParser.exception_handling import DocumentParsingError

nest_asyncio.apply()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)  # 创建日志记录器


class EnterpriseDocParser:
    """
    基于 LlamaParse 最新引擎的企业级文档解析服务
    """
    file_max_size_mb = 50
    support_file_types = [".pdf", ".docx", ".xlsx", ".txt", ".md", ".png", ".jpg", ".jpeg", ".svg"]

    def __init__(self):
        self.api_key = settings.llm_key.llamaParse
        if not self.api_key:
            logger.error("⚠️ 请在 config/config.yaml 中配置 LlamaParse API Key")

    def _validate_file(self, file_path: Path):
        """文件校验"""
        if not file_path.exists():
            raise FileNotFoundError(f"⚠️ 找不到文件 {file_path}。")  # 抛出文件不存在异常

        if file_path.suffix.lower() not in self.support_file_types:
            raise ValueError(f"⚠️ 不支持的文件类型 {file_path.suffix}。")  # 抛出文件类型不支持异常

        file_size_mb = os.path.getsize(file_path) / 1024 / 1024  # MB
        if file_size_mb == 0:
            raise ValueError(f"⚠️ 文件 {file_path} 为空。")  # 抛出文件为空异常
        elif file_size_mb > self.file_max_size_mb:
            raise ValueError(f"⚠️ 文件 {file_path} 超过 {self.file_max_size_mb}MB。")  # 抛出文件过大异常

        logger.info(f"文件检验通过: {file_path} ({file_size_mb:.2f} MB)")

    def _build_parser(self, mode: str = "markdown") -> LlamaParse:
        """
        工厂方法：根据需求配置 LlamaParse 实例
        :param mode: "markdown" (RAG标准) 或 "text" 或 "json" (高阶提取)
        """
        return LlamaParse(
            api_key=self.api_key,
            result_type=mode,  # 输出格式

            auto_mode=True,  # 系统自动判断使用哪个解析引擎
            auto_mode_trigger_on_image_in_page=True,  # 页面有图片时，自动升级
            auto_mode_trigger_on_table_in_page=True,  # 页面有表格时，自动升级

            continuous_mode=True,  # 针对超长文档，防止中间解析中断，自动处理分片逻辑
            high_res_ocr=True,  # 针对图表使用高精度OCR

            num_workers=4,  # 并发控制

            job_timeout_in_seconds=3 * 60,  # 超时设置，防止任务卡死

            page_error_tolerance=0.1,  # 单页错误容忍度，超过阈值则跳过
            replace_failed_page_mode="raw_text",  # 失败的页面自动降级为只提取底层原始文本 (Raw Text)

            # [调试] 生产环境设为 False，开发环境设为 True 可避免重复消耗 Credit
            invalidate_cache=settings.llama_parser.invalidate_cache,

            language="en",  # 语言
        )

    @retry(
        stop=stop_after_attempt(2),  # 最多尝试 2 次
        wait=wait_exponential(multiplier=2, min=4, max=20),  # 等待 4-20 秒 重试
        retry=retry_if_exception_type((TimeoutError, ConnectionError)),  # 错误类型
        reraise=True  # 抛出异常
    )
    async def _execute_parsing(self, parser: LlamaParse, file_path: str) -> list[Document]:
        """执行API调用，隔离网络重试逻辑"""
        return await parser.aload_data(file_path)

    async def parse_file(self, file_path: str, instruction: str = "") -> str:
        """
        执行解析任务，支持指令注入
        """
        start_time = time.time()
        path_obj = Path(file_path)

        # if path_obj.suffix != ".pdf":
        #     convert(file_path, r"D:\学习笔记\langchain\rag_upper\document\convert\output.pdf")
        #     file_path = r"D:\学习笔记\langchain\rag_upper\document\convert\output.pdf"

        try:
            self._validate_file(path_obj)  # 文件校验
            logger.info(f"🚀 开始解析任务: {path_obj.name}[Trace ID: {id(self)}]")

            parser = self._build_parser()
            # 指令注入 像 Prompt 一样控制解析行为，这是 V2 最强大的地方
            if instruction:
                parser.system_prompt = instruction
            else:
                parser.system_prompt = (
                    "You are a highly accurate academic document transcription engine. "
                    "Your ONLY task is to transcribe the document exactly as it appears into Markdown format. "
                    "RULES: "
                    "1. DO NOT summarize, extract, or answer questions. "
                    "2. Preserve all paragraphs, headings, and reading order perfectly. "
                    "3. For tables, preserve the exact row and column structure using standard Markdown table syntax. "
                    "4. Convert all mathematical equations and formulas into LaTeX format (e.g., $E=mc^2$ or $$...$$)."
                )
            # 调用API进行解析
            docs = await self._execute_parsing(parser, file_path)

            documents = "\n\n".join([doc.text for doc in docs])

            if not documents:
                logger.error(f"⚠️ 解析完成，但是没有提取到任何内容: {path_obj.name}")
                return []
            logger.info(
                f"🚀 解析完成: {path_obj.name} ({len(docs)} pages; "
                f"耗时: {time.time() - start_time:.1f}s)")
            return documents
        except FileNotFoundError as fe:
            logger.error(f"⚠️ 文件 {path_obj.name} 不存在: {fe}")
            raise DocumentParsingError(f"文档不存在：{str(fe)}") from fe
        except ValueError as ve:
            logger.error(f"⚠️ 文件 {path_obj.name} 检验错误: {ve}")
            raise DocumentParsingError(f"文件校验错误：{str(ve)}") from ve
        except (TimeoutError, ConnectionError) as ne:
            logger.error(f"❌ 网络/API 终态超时: {str(ne)} | 耗时: {time.time() - start_time:.1f}s")
            raise DocumentParsingError("文档解析服务当前不可用，请稍后再试") from ne
        except Exception as e:
            logger.error(f"❌ 发生未知严重错误: {str(e)}")
            raise DocumentParsingError(f"文档解析过程中发生系统错误：{str(e)}") from e


async def parse_file_by_llamaParse(file_path: str):
    """
    使用llamaparse解析文档
    :param file_path:
    :return:
    """
    parser_service = EnterpriseDocParser()
    try:
        return await parser_service.parse_file(file_path)
    except DocumentParsingError as e:
        logger.error(f"❌ 文档解析错误: {str(e)}")


def word_to_pdf(word_file_path: str, pdf_file_path: str):
    """word文档转为PDF"""
    convert(word_file_path, pdf_file_path)
```

## File: `multi_domain_enterprise_project\rag\documentParser\officeparser.py`

```py
import asyncio
import os
import logging
import time
from pathlib import Path
from markitdown import MarkItDown
from multi_domain_enterprise_project.rag.documentParser.exception_handling import DocumentParsingError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class EnterpriseOfficeParser:
    """
    适用场景：.docx, .pptx, .xlsx, .html, .csv
    """

    file_max_size_mb = 50
    support_file_types = [".docx", ".xlsx", ".xls", ".pptx", ".txt", ".md", ".csv", ".html"]

    def __init__(self):
        pass

    def _validate_file(self, file_path: Path):
        """
        检查文件格式是否支持
        """
        if not file_path.exists():
            raise FileNotFoundError(f"找不到文件: {file_path}")
        if not file_path.suffix in self.support_file_types:
            raise ValueError(f"不支持的文件格式: {file_path.suffix}")
        file_size_mb = os.path.getsize(file_path) / 1024 / 1024  # MB
        if file_size_mb == 0:
            raise ValueError(f"⚠️ 文件 {file_path} 为空。")
        if file_size_mb > self.file_max_size_mb:
            raise ValueError(f"⚠️ 文件 {file_path} 超过 {self.file_max_size_mb}MB。")

    async def parse_file(self, file_path: str) -> str:
        """
        解析 Office 文档，返回 LlamaIndex Document 列表。
        注意：Office 文档通常没有物理“页码”的严格概念，所以一般作为一个大 Document 返回，
        后续再由 LlamaIndex 的 MarkdownNodeParser 进行文本分块(Chunking)。
        """

        md_converter = MarkItDown()
        loop = asyncio.get_event_loop()

        path_obj = Path(file_path)
        start_time = time.time()

        self._validate_file(path_obj)

        logger.info(f"🚀 开始解析任务: {path_obj.name}[Trace ID: {id(self)}]")

        try:
            # 转换为 Markdown
            result = await loop.run_in_executor(
                None,
                md_converter.convert,
                file_path
            )
            documents = result.text_content

            if not documents:
                logger.error(f"⚠️ 解析完成，但是没有提取到任何内容: {path_obj.name}")
                return ''

            logger.info(
                f"🚀 解析完成: {path_obj.name} ({len(documents)} pages; "
                f"耗时: {time.time() - start_time:.1f}s)")
            return documents

        except FileNotFoundError as fe:
            logger.error(f"⚠️ 文件 {path_obj.name} 不存在: {fe}")
            raise DocumentParsingError(f"文档不存在：{str(fe)}") from fe
        except ValueError as ve:
            logger.error(f"⚠️ 文件 {path_obj.name} 检验错误: {ve}")
            raise DocumentParsingError(f"文件校验错误：{str(ve)}") from ve
        except Exception as e:
            logger.error(f"❌ 发生未知严重错误: {str(e)}")
            raise DocumentParsingError(f"文档解析过程中发生系统错误：{str(e)}") from e


async def parse_file_by_officeParse(file_path: str) -> str:
    """
    使用 OfficeParser 解析 Office 文档，
    """
    parser = EnterpriseOfficeParser()
    try:
        return await parser.parse_file(file_path)
    except DocumentParsingError as e:
        logger.error(f"❌ 文档解析错误: {str(e)}")


if __name__ == '__main__':
    res = asyncio.run(parse_file_by_officeParse(r"/document/rag中处理excel表格.txt"))
    print(res)
```

## File: `multi_domain_enterprise_project\rag\documentParser\parser_route.py`

```py
import os
import time
import logging
import asyncio
import zipfile
from pathlib import Path

import fitz

from multi_domain_enterprise_project.rag.documentParser.llamaparser import EnterpriseDocParser
from multi_domain_enterprise_project.rag.documentParser.officeparser import EnterpriseOfficeParser
from multi_domain_enterprise_project.rag.documentParser.pymupdfparser import EnterprisePyMuPDFParser
from multi_domain_enterprise_project.rag.documentParser.qwenparser import EnterpriseLocalVLMParser
from multi_domain_enterprise_project.rag.documentParser.exception_handling import DocumentParsingError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class DocumentParserRouter:
    """
    企业级文档解析智能路由器
    负责分析文档特征，将解析任务分发给最合适的底层解析器，平衡成本、延迟与质量。
    """

    def __init__(self, mode: str = "auto"):
        """
        :param mode: 解析模式
            - "auto": 智能路由（默认：平衡成本、速度、精度，动态分发）
            - "fast": 本地极速模式（不调用云端 API，绝对省钱、数据绝对不出域保密）
            - "accurate": 高精度模式（无视成本，只要是复杂文档无脑扔给云端大模型）
        """
        self.mode = mode

        # 懒加载初始化解析器，避免启动路由器时占用过多内存或显存
        self._office_parser = None
        self._pymupdf_parser = None
        self._qwen_parser = None
        self._llama_parser = None

    @property
    def office_parser(self):
        if not self._office_parser:
            logger.info("🔧 初始化 [EnterpriseOfficeParser] (MarkItDown)")
            self._office_parser = EnterpriseOfficeParser()
        return self._office_parser

    @property
    def pymupdf_parser(self):
        if not self._pymupdf_parser:
            logger.info("🔧 初始化 [EnterprisePyMuPDFParser] (PyMuPDF4LLM)")
            self._pymupdf_parser = EnterprisePyMuPDFParser()
        return self._pymupdf_parser

    @property
    def qwen_parser(self):
        if not self._qwen_parser:
            logger.info("🔧 初始化 [EnterpriseLocalVLMParser] (Qwen2.5-VL)")
            self._qwen_parser = EnterpriseLocalVLMParser()
        return self._qwen_parser

    @property
    def llama_parser(self):
        if not self._llama_parser:
            logger.info("🔧 初始化 [EnterpriseDocParser] (LlamaParse)")
            self._llama_parser = EnterpriseDocParser()
        return self._llama_parser

    def _probe_office(self, file_path: str) -> dict:
        """
        【Office核心探测器】花 0.005 秒解析 OOXML 目录树
        通过计算 media (图片) 和 charts (图表) 文件夹内的文件数量，判断复杂度
        """
        image_count = 0
        chart_count = 0

        try:
            # 直接将 docx/pptx/xlsx 当作 zip 读取目录树 (极快，不占用内存)
            with zipfile.ZipFile(file_path, 'r') as z:
                file_list = z.namelist()

                for f in file_list:
                    # 匹配图片资源
                    if f.startswith(('word/media/', 'ppt/media/', 'xl/media/')):
                        image_count += 1
                    # 匹配原生图表 (柱状图、饼图等)
                    elif f.startswith(('word/charts/', 'ppt/charts/', 'xl/charts/')):
                        chart_count += 1

            logger.info(f"📊 Office探针分析完成: 图片={image_count}张, 图表={chart_count}个")

            # 判断标准：如果有超过 3 张图，或者只要存在 1 个图表，就认为是复杂文档
            is_complex = chart_count > 0 or image_count > 3

            return {
                "image_count": image_count,
                "chart_count": chart_count,
                "is_complex": is_complex
            }
        except zipfile.BadZipFile:
            # 如果不是标准的 OOXML (比如老版本的 .doc 或已被破坏的结构)，安全起见走复杂路线
            logger.warning(f"⚠️ 无法将文件作为 ZIP 读取(可能是旧版 .doc)，默认判定为复杂模式")
            return {"is_complex": True}
        except Exception as e:
            logger.warning(f"⚠️ Office 探针分析失败: {e}")
            return {"is_complex": True}

    def _probe_pdf(self, file_path: str) -> str:
        """
        【企业级 PDF 核心探测器 V2】花 0.05 秒精准侦查 PDF 构成
        采用分层抽样、排版碎片率计算，输出绝对互斥的路由建议。
        返回结果为字符串枚举: 'scanned' | 'complex' | 'simple'
        """
        try:
            doc = fitz.open(file_path)
            total_pages = len(doc)

            # 1. 解决【采样偏差】：分层抽样
            # 避免被封面和目录欺骗，最多抽样 3 页：首页、中间页、尾页
            if total_pages <= 3:
                pages_to_check = list(range(total_pages))
            else:
                pages_to_check = list(range(1, total_pages))  # 跳过封面(0)，从第2页开始

            total_chars = 0
            total_images = 0
            total_drawings = 0
            total_blocks = 0  # 文本块数量，用于评估排版碎片率

            for p_idx in pages_to_check:
                page = doc[p_idx]

                # 获取纯文本
                text = page.get_text("text").strip()
                total_chars += len(text)

                # 获取图片和矢量线框
                total_images += len(page.get_images(full=True))
                total_drawings += len(page.get_drawings())

                # 复杂的双栏、三栏、嵌套表格，会导致 block 数量激增
                blocks = page.get_text("blocks")
                total_blocks += len(blocks)

            doc.close()

            # 2. 解决【未均值化】：全部转换为单页平均值
            num_sampled = len(pages_to_check)
            avg_chars = total_chars / num_sampled
            avg_images = total_images / num_sampled
            avg_drawings = total_drawings / num_sampled
            avg_blocks = total_blocks / num_sampled

            logger.info(f"📊 PDF探针(抽样{num_sampled}页): "
                        f"均字={avg_chars:.0f}, 均图={avg_images:.1f}, "
                        f"均矢量={avg_drawings:.1f}, 均文本块={avg_blocks:.1f}")

            # 3. 解决【标志位冲突】与【阈值死板】：使用互斥的优先级决策树

            # 优先级 1：纯扫描件探测 (Scanned)
            # 提高容错率(150字)，防止扫描件OCR噪点导致的误判；同时必须包含图片
            if avg_chars < 150 and avg_images >= 0.5:
                return "scanned"

            # 优先级 2：复杂版面探测 (Complex)
            # 满足以下任一条件即可判定为复杂版面：
            # a. 矢量图过多 (平均大于 5，通常是数据图表、线框表格)
            # b. 图片过多 (平均大于 2，通常是 PPT 导出的 PDF)
            # c. 【核心】文本碎片率极高 (平均大于 40 块，必然是多栏排版或密集表格)
            if avg_drawings > 5 or avg_images > 2 or avg_blocks > 40:
                return "complex"

            # 优先级 3：简单文本兜底 (Simple)
            # 不满足上述条件，一律视为对轻量解析器友好的原生数字文档
            return "simple"

        except Exception as e:
            logger.warning(f"⚠️ PDF 探针分析失败，强制降级为 complex 处理: {e}")
            return "complex"  # 探针异常时，安全降级给最强的解析器

    async def route_and_parse(self, file_path: str) -> str:
        """
        接收文件路径，执行路由分发并返回提取的 Markdown/Text 字符串
        """
        path_obj = Path(file_path)
        ext = path_obj.suffix.lower()

        start_time = time.time()
        logger.info(f"🚦 路由器接收到任务: {path_obj.name} | 策略模式: [{self.mode.upper()}]")

        if not path_obj.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        try:
            # ================== 1. Office 文档路由 ==================
            if ext in [".docx", ".xlsx", ".xls", ".pptx"]:
                if self.mode == "accurate":
                    logger.info("👉 决策: 强制高精模式，分发给 [LlamaParser]")
                    return await self.llama_parser.parse_file(file_path)

                # 特别关照 PPT：幻灯片天生排版极其复杂，文本框随意放置，极易丢失空间语义
                if ext == ".pptx":
                    if self.mode == "fast":
                        logger.info("👉 决策: PPT幻灯片 (极速模式拦截)，牺牲排版交由本地 [OfficeParser]")
                        return await self.office_parser.parse_file(file_path)
                    else:
                        logger.info("👉 决策: PPT幻灯片 (Auto模式)，为保留图表排版，分发给懂视觉的 [LlamaParser]")
                        return await self.llama_parser.parse_file(file_path)

                # Word / Excel 启用探针
                probe_result = self._probe_office(file_path)

                if probe_result["is_complex"]:
                    if self.mode == "fast":
                        logger.info("👉 决策: 复杂Office (极速模式拦截)，舍弃图表，使用本地 [OfficeParser]")
                        return await self.office_parser.parse_file(file_path)
                    else:
                        logger.info("👉 决策: 复杂Office (Auto模式)，内含多图/图表，分发给 [LlamaParser]")
                        return await self.llama_parser.parse_file(file_path)
                else:
                    logger.info("👉 决策: 简单纯文本Office，安全分发给极速本地 [OfficeParser]")
                    return await self.office_parser.parse_file(file_path)

            # ================== 2. 图片文档路由 ==================
            elif ext in [".png", ".jpg", ".jpeg", ".bmp"]:
                if self.mode == "accurate":
                    logger.info("👉 决策: 强制高精模式，分发给[LlamaParser]")
                    return await self.llama_parser.parse_file(file_path)
                else:
                    logger.info("👉 决策: 图片文件 (Auto/Fast)，分发给本地视觉大模型[QwenParser]")
                    return await self.qwen_parser.parse_file(file_path)

            # ================== 3. PDF 动态路由 ==================
            elif ext == ".pdf":
                if self.mode == "accurate":
                    logger.info("👉 决策: 强制高精模式，分发给 [LlamaParser]")
                    return await self.llama_parser.parse_file(file_path)

                    # 启用 V2 探针，拿到唯一决策指令
                route_decision = self._probe_pdf(file_path)

                if route_decision == "scanned":
                    if self.mode == "fast":
                        logger.info("👉 决策: PDF 扫描件 (极速模式)，分发给本地视觉[QwenParser]")
                        return await self.qwen_parser.parse_file(file_path)
                    else:
                        logger.info("👉 决策: PDF 扫描件 (Auto)，分发给[LlamaParser]")
                        return await self.llama_parser.parse_file(file_path)

                elif route_decision == "complex":
                    if self.mode == "fast":
                        logger.info("👉 决策: 复杂排版 PDF (极速拦截)，强制本地 [PyMuPDFParser]")
                        return await self.pymupdf_parser.parse_file(file_path)
                    else:
                        logger.info("👉 决策: 复杂排版 PDF (Auto)，分发给云端 [LlamaParser]")
                        return await self.llama_parser.parse_file(file_path)

                elif route_decision == "simple":
                    logger.info("👉 决策: 简单原生 PDF，安全分发给极速本地 [PyMuPDFParser]")
                    return await self.pymupdf_parser.parse_file(file_path)

            # ================== 4. 纯文本路由 ==================
            elif ext in [".txt", ".md", ".csv", ".json"]:
                logger.info("👉 决策: 纯文本格式，交由[OfficeParser] (MarkItDown) 快速提取")
                return await self.office_parser.parse_file(file_path)

            else:
                raise ValueError(f"不支持的文件扩展名: {ext}")

        except Exception as e:
            logger.error(f"❌ 路由解析发生异常: {e}")
            # LlamaParse 兜底重试
            if self.mode != "fast" and ext in [".pdf", ".docx", ".pptx", ".xlsx", ".png", ".jpg"]:
                logger.warning("🔄 触发兜底机制: 尝试启用云端 LlamaParse 进行重试...")
                try:
                    return await self.llama_parser.parse_file(file_path)
                except Exception as fallback_e:
                    logger.error(f"❌ 兜底解析亦失败: {fallback_e}")
                    raise DocumentParsingError(f"所有路由均告失败。原始错误: {e}, 兜底错误: {fallback_e}")
            # 抛出最终业务异常
            raise DocumentParsingError(f"路由解析任务中断: {str(e)}")


if __name__ == "__main__":
    async def test_router():
        # 初始化路由器，采用智能模式
        router = DocumentParserRouter(mode="auto")

        # 将这里的路径替换为你电脑里的实际测试文件
        test_files = [
            r'D:\学习笔记\langchain\rag_upper\document\transformer.pdf',
        ]

        for file in test_files:
            if os.path.exists(file):
                print("\n" + "=" * 60)
                try:
                    res = await router.route_and_parse(file)
                    print(f"✅ [{os.path.basename(file)}] 解析成功，提取字数: {len(res)}")
                    # 打印前 200 个字符预览
                    print(f"预览:\n{res[:200]}...")
                except Exception as e:
                    print(f"❌ 测试失败: {e}")
            else:
                print(f"\n⚠️ 测试文件不存在跳过: {file}")


    # 运行异步事件循环
    asyncio.run(test_router())
```

## File: `multi_domain_enterprise_project\rag\documentParser\pymupdfparser.py`

```py
import asyncio
import os
import time

import logging
from pathlib import Path
from multi_domain_enterprise_project.rag.documentParser.exception_handling import DocumentParsingError
from langchain_pymupdf4llm import PyMuPDF4LLMLoader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class EnterprisePyMuPDFParser:
    """
    企业级轻量级 PDF 解析器 (基于 PyMuPDF)
    适用场景：纯数字原生 PDF、合同、规章制度、无复杂表格的论文
    """

    file_max_size_mb = 50
    support_file_types = [".pdf"]

    def __init__(self):
        pass

    def _validate_file(self, file_path: Path):
        """
        检查文件格式是否支持
        """
        if not file_path.exists():
            raise FileNotFoundError(f"找不到文件: {file_path}")
        if not file_path.suffix in self.support_file_types:
            raise ValueError(f"不支持的文件格式: {file_path.suffix}")
        file_size_mb = os.path.getsize(file_path) / 1024 / 1024  # MB
        if file_size_mb == 0:
            raise ValueError(f"⚠️ 文件 {file_path} 为空。")
        if file_size_mb > self.file_max_size_mb:
            raise ValueError(f"⚠️ 文件 {file_path} 超过 {self.file_max_size_mb}MB。")

    async def parse_file(self, file_path: str) -> str:
        """
        解析原生 PDF，按页返回 Document 列表
        """
        path_obj = Path(file_path)
        start_time = time.time()

        self._validate_file(path_obj)

        logger.info(f"🚀 开始解析任务: {path_obj.name}[Trace ID: {id(self)}]")

        try:
            document_parser = PyMuPDF4LLMLoader(path_obj)
            documents = await document_parser.aload()

            if not documents:
                logger.error(f"⚠️ 解析完成，但是没有提取到任何内容: {path_obj.name}")
                return ''

            docs = "\n".join([doc.page_content for doc in documents])

            logger.info(
                f"🚀 解析完成: {path_obj.name} ({len(documents)} pages; "
                f"耗时: {time.time() - start_time:.1f}s)")
            return docs
        except FileNotFoundError as fe:
            logger.error(f"⚠️ 文件 {path_obj.name} 不存在: {fe}")
            raise DocumentParsingError(f"文档不存在：{str(fe)}") from fe
        except ValueError as ve:
            logger.error(f"⚠️ 文件 {path_obj.name} 检验错误: {ve}")
            raise DocumentParsingError(f"文件校验错误：{str(ve)}") from ve
        except Exception as e:
            logger.error(f"❌ 发生未知严重错误: {str(e)}")
            raise DocumentParsingError(f"文档解析过程中发生系统错误：{str(e)}") from e


async def parse_file_by_pymupdf(file_path: str) -> str:
    """
    使用pymupdf解析 PDF
    """
    parser = EnterprisePyMuPDFParser()
    try:
        return await parser.parse_file(file_path)
    except DocumentParsingError as e:
        logger.error(f"❌ 文档解析错误: {str(e)}")


if __name__ == '__main__':
    res = asyncio.run(parse_file_by_pymupdf(r'/document/transformer.pdf'))
    print(res)



```

## File: `multi_domain_enterprise_project\rag\documentParser\qwenparser.py`

```py
import os
import time
import logging
import asyncio
from pathlib import Path
from typing import Union

import ollama
from multi_domain_enterprise_project.rag.documentParser.exception_handling import DocumentParsingError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class EnterpriseLocalVLMParser:
    """
    企业级本地视觉大模型解析器 (基于 Ollama + Qwen2.5-VL)
    适用场景：复杂的本地表格、带格式的文档、简单的多模态理解
    """

    file_max_size_mb = 50
    support_file_types = [".png", ".jpg", ".jpeg", ".pdf"]

    def __init__(self, model_name: str = 'qwen2.5vl:3b'):
        self.model_name = model_name
        # 测试连接
        try:
            ollama.list()
            logger.info(f"✅ 已连接到本地 Ollama，使用模型: {self.model_name}")
        except Exception as e:
            logger.error("❌ 无法连接到 Ollama，请确保 Ollama 服务已启动。")
            raise ConnectionError("Ollama 服务未响应") from e

    def _validate_file(self, file_path: Path):
        if not file_path.exists():
            raise FileNotFoundError(f"找不到文件: {file_path}")
        if not file_path.suffix in self.support_file_types:
            raise ValueError(f"不支持的文件格式: {file_path.suffix}")
        file_size_mb = os.path.getsize(file_path) / 1024 / 1024  # MB
        if file_size_mb == 0:
            raise ValueError(f"⚠️ 文件 {file_path} 为空。")
        if file_size_mb > self.file_max_size_mb:
            raise ValueError(f"⚠️ 文件 {file_path} 超过 {self.file_max_size_mb}MB。")

    def _process_single_image(self, image_input: Union[str, bytes]) -> str:
        """调用 Ollama 进行单图推理"""
        ocr_prompt = (
            "必须使用中文回答。"
            "先概括图片的组成，再详细描述图片中的每个组成部分。"
        )

        try:
            response = ollama.chat(
                model=self.model_name,
                messages=[{
                    'role': 'user',
                    'content': ocr_prompt,
                    'images': [image_input]
                }]
            )
            return response.message.content
        except Exception as e:
            logger.error(f"Ollama 推理失败: {e}")
            return ""

    async def parse_file(self, file_path: str) -> str:
        """执行解析"""
        path_obj = Path(file_path)
        self._validate_file(path_obj)

        start_time = time.time()
        logger.info(f"🤖 开始 Qwen2.5-VL 本地解析: {path_obj.name}")

        loop = asyncio.get_event_loop()
        extracted_results = []

        try:
            content = await loop.run_in_executor(
                None, self._process_single_image, str(path_obj)
            )
            extracted_results.append(content)

            full_text = "\n\n".join(extracted_results)

            logger.info(f"✅ 解析完成: {path_obj.name} (耗时: {time.time() - start_time:.1f}s)")
            return full_text

        except FileNotFoundError as fe:
            logger.error(f"⚠️ 文件 {path_obj.name} 不存在: {fe}")
            raise DocumentParsingError(f"文档不存在：{str(fe)}") from fe
        except ValueError as ve:
            logger.error(f"⚠️ 文件 {path_obj.name} 检验错误: {ve}")
            raise DocumentParsingError(f"文件校验错误：{str(ve)}") from ve
        except Exception as e:
            logger.error(f"❌ 发生未知严重错误: {str(e)}")
            raise DocumentParsingError(f"文档解析过程中发生系统错误：{str(e)}") from e


async def parse_file_by_qwen2_5_vl(file_path: str) -> str:
    """
    使用 Qwen2.5-VL 进行本地解析
    """
    parser_service = EnterpriseLocalVLMParser()
    try:
        return await parser_service.parse_file(file_path)
    except DocumentParsingError as e:
        logger.error(f"❌ 文档解析错误: {str(e)}")


if __name__ == "__main__":
    res = asyncio.run(parse_file_by_qwen2_5_vl(r'/document/transformer.png'))
    print(res)
```

## File: `multi_domain_enterprise_project\rag\documentParser\__init__.py`

```py

```

## File: `multi_domain_enterprise_project\rag\graph\graph_db.py`

```py
# graph_db.py
import logging
from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore

# 增加这一行，设置日志级别为 INFO，并简单配置输出格式
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


class EnterpriseGraphStore:
    def __init__(self):
        # 实际使用中替换为配置文件 setting.neo4j.url 等
        self.url = "bolt://localhost:7687"
        self.username = "neo4j"
        self.password = "12345678"

    def get_graph_store(self) -> Neo4jPropertyGraphStore:
        try:
            graph_store = Neo4jPropertyGraphStore(
                username=self.username,
                password=self.password,
                url=self.url,
            )
            logger.info("✅ 成功连接 Neo4j 图数据库")
            return graph_store
        except Exception as e:
            logger.error(f"❌ 连接 Neo4j 失败: {e}")
            raise


if __name__ == '__main__':
    graph_store = EnterpriseGraphStore()
    graph_store.get_graph_store()
    pass
```

## File: `multi_domain_enterprise_project\rag\graph\ingestion_graph.py`

```py
import logging
from typing import List

from llama_index.core import PropertyGraphIndex
from llama_index.core.schema import BaseNode, QueryBundle
from llama_index.core.indices.property_graph import SimpleLLMPathExtractor, LLMSynonymRetriever, VectorContextRetriever
from llama_index.core.vector_stores import MetadataFilter, FilterOperator, MetadataFilters, FilterCondition
from llama_index.embeddings.langchain import LangchainEmbedding
from llama_index.llms.dashscope import DashScope
from llama_index.llms.openai_like import OpenAILike
from llama_index.postprocessor.flag_embedding_reranker import FlagEmbeddingReranker

from config import settings
from multi_domain_enterprise_project.rag.graph.graph_db import EnterpriseGraphStore
from multi_domain_enterprise_project.rag.ollama_embedding import ollama_embedding_function

logger = logging.getLogger(__name__)


class GraphStorePipelineService:
    def __init__(self):
        # 1. 准备 Embedding
        self.embed_model = LangchainEmbedding(ollama_embedding_function)

        # 2. 准备大语言模型 (用于抽取，推荐用大参数模型)
        self.llm = DashScope(
            model_name="qwen-max",
            api_key=settings.llm_key.qwen
        )

        # 3. 配置图谱存储
        self.graph_store = EnterpriseGraphStore().get_graph_store()

        # 4. 配置三元组抽取器
        # SimpleLLMPathExtractor 会提取实体及其关联，构建诸如 (李四, 汇报给, 张三) 的关系
        self.kg_extractor = SimpleLLMPathExtractor(
            llm=self.llm,
            max_paths_per_chunk=10,  # 每个文本块最多抽取10个关系
            num_workers=2  # 并发抽取
        )

    async def insert_nodes(self, nodes: List[BaseNode]):
        """执行图谱抽取和入库"""
        if not nodes:
            return

        logger.info(f"🚀 开始 GraphRAG 知识抽取与入库，共 {len(nodes)} 个切片...")

        for node in nodes:
            for key, value in list(node.metadata.items()):
                # 1. 如果是空值，Neo4j不支持，直接删除该键
                if value is None:
                    del node.metadata[key]
                    continue

                # 2. 如果是列表，遍历列表里的每个元素
                if isinstance(value, list):
                    cleaned_list = []
                    for item in value:
                        # 只要不是(字符串, 整数, 浮点数, 布尔值)，统统强转为字符串
                        if not isinstance(item, (str, int, float, bool)):
                            cleaned_list.append(str(item))
                        else:
                            cleaned_list.append(item)
                    node.metadata[key] = cleaned_list

                # 3. 如果是单值，且不是基础类型（比如 WindowsPath, dict 等），直接转为字符串
                elif not isinstance(value, (str, int, float, bool)):
                    node.metadata[key] = str(value)

        try:
            # PropertyGraphIndex.from_nodes 会自动执行:
            # 文本块 -> 抽取器(LLM) -> 生成图结构 -> 向量化实体/文本块 -> 存入图数据库
            index = PropertyGraphIndex(
                nodes,  # 节点列表
                llm=self.llm,  # LLM
                use_async=True,  # 异步执行
                embed_model=self.embed_model,
                kg_extractors=[self.kg_extractor],  # 三元组抽取器
                property_graph_store=self.graph_store,  # 图谱存储
                show_progress=True,  # 显示进度
            )
            logger.info("✅ GraphRAG 图谱全量入库成功！")
        except Exception as e:
            logger.error(f"❌ 图谱入库失败: {e}")
            raise


class GraphRetrieverService:
    def __init__(self):
        # 1. 准备 Embedding
        self.embed_model = LangchainEmbedding(ollama_embedding_function)

        # 2. 准备大语言模型 (用于抽取，推荐用大参数模型)
        self.llm = DashScope(
            model_name="qwen-max",
            api_key=settings.llm_key.qwen
        )

        # 3. 配置图谱存储
        self.graph_store = EnterpriseGraphStore().get_graph_store()

        # 获取数据库索引，用于检索
        self.index = PropertyGraphIndex.from_existing(
            property_graph_store=self.graph_store,
            llm=self.llm,
            embed_model=self.embed_model,
        )

        # BGE-Reranker 来精排子图和文本
        self.reranker = FlagEmbeddingReranker(
            top_n=3, model="D:/Environment/model/bge-reranker-v2-m3", use_fp16=True
        )

    async def retrieve_answer(self, query_str: str, filters_dict: dict = None):
        logger.info(f"⚙️ 正在向 Neo4j 图数据库 发起混合检索: {query_str}。 过滤字段: {filters_dict}")

        filters = None
        # 构造元数据过滤器
        if filters_dict:
            # 先把字典里 value 为 None 的键值对剔除掉！
            cleaned_filters = {str(k): str(v) for k, v in filters_dict.items() if v is not None}

            if cleaned_filters:
                filter_list = [
                    MetadataFilter(key=k, value=v, operator=FilterOperator.IN if k == 'acl' else FilterOperator.EQ)
                    for k, v in cleaned_filters.items()
                ]

                filters = MetadataFilters(
                    filters=filter_list,
                    condition=FilterCondition.AND
                )

        # 策略 1: 基于 LLM 的同义词扩展和图谱实体  关键词检索
        synonym_retriever = LLMSynonymRetriever(
            self.index.property_graph_store,
            llm=self.llm,
            include_text=True
        )

        # 策略 2: 基于向量的图谱内容检索 (匹配节点描述或边描述)  向量语义检索
        vector_retriever = VectorContextRetriever(
            self.index.property_graph_store,
            embed_model=self.embed_model,
            include_text=True,
            similarity_top_k=30,
            filters=filters
        )

        # 构建自定义检索器 (LlamaIndex 自带的混合检索功能)
        hybrid_retriever = self.index.as_retriever(
            sub_retrievers=[synonym_retriever, vector_retriever]
        )

        # 多路召回与融合(内部使用RRF重排)
        final_nodes = await hybrid_retriever.aretrieve(query_str)

        if not final_nodes:
            logger.warning("⚠️ 检索结果为空！")
            return []

        # 2. Reranker 精排
        query_bundle = QueryBundle(query_str=query_str)
        final_nodes = self.reranker.postprocess_nodes(
            nodes=final_nodes,
            query_bundle=query_bundle
        )

        return await format_graph_retrieval_results(final_nodes)


async def format_graph_retrieval_results(nodes):
    """
    格式化 GraphRAG 检索结果：将三元组与文本块区分，但保持 Header 风格一致
    """
    if not nodes:
        return "【图数据库检索】: 未找到相关关联事实。"

    kg_parts = ["### 🕸️ 知识图谱关联事实："]
    text_parts = ["### 📄 图谱关联参考文本："]

    seen_ids = set()
    for node_with_score in nodes:
        node = node_with_score.node
        if node.node_id in seen_ids: continue
        seen_ids.add(node.node_id)

        score = node_with_score.score
        file_name = node.metadata.get('file_name', '未知文件')
        content = node.get_content().strip()

        # 判定是三元组事实还是原始文本
        if "facts extracted from the provided text" in content:
            # 这里的 content 已经包含了 "Here are some facts..."
            header = f"--- [来源: {file_name} | 类型: 关系事实 | 匹配分值: {score:.4f}] ---"
            kg_parts.append(f"{header}\n{content}")
        else:
            header = f"--- [来源: {file_name} | 类型: 关联文本 | 匹配分值: {score:.4f}] ---"
            text_parts.append(f"{header}\n{content}")

    # 合并输出
    result = []
    if len(kg_parts) > 1: result.append("\n\n".join(kg_parts))
    if len(text_parts) > 1: result.append("\n\n".join(text_parts))

    return "\n\n".join(result)
```

## File: `multi_domain_enterprise_project\rag\milvus\ingestion_milvus.py`

```py
import logging
from typing import List

from llama_index.core import VectorStoreIndex, QueryBundle
from llama_index.core.schema import BaseNode
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterCondition, FilterOperator
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.postprocessor.flag_embedding_reranker import FlagEmbeddingReranker

from multi_domain_enterprise_project.rag.milvus.milvus_db import EnterpriseMilvusStore
from config import settings

logger = logging.getLogger(__name__)


# 全局共享的基础配置获取函数
def get_base_index(collection_name: str):
    """提取公共的连接初始化代码"""
    # 连接本地向量模型
    embed_model = OllamaEmbedding(
        model_name='qwen3-embedding:4b',
        base_url="http://127.0.0.1:11434",
    )
    # 创建milvus管理器
    milvus_manager = EnterpriseMilvusStore(
        collection_name=collection_name,
        dim=settings.milvus.dims
    )
    # 获取存储上下文
    storage_context = milvus_manager.get_storage_context()
    # 获取向量索引
    index = VectorStoreIndex.from_vector_store(
        vector_store=storage_context.vector_store,
        embed_model=embed_model
    )
    return index


class MilvusStorePipelineService:
    """数据入库服务 (无状态，轻量级，不加载重排模型)
    """

    def __init__(self, collection_name: str = "company_knowledge_base"):
        self.index = get_base_index(collection_name)

    async def insert_nodes(self, nodes: List[BaseNode], batch_size: int = 100):
        if not nodes:
            return

        logger.info(f"🚀 开始增量入库 {len(nodes)} 个切片 (Batch Size: {batch_size})...")
        try:
            # 批处理写入 防 gRPC 超载
            for i in range(0, len(nodes), batch_size):
                batch = nodes[i: i + batch_size]
                # 因为 node.id_ 是 hash，Milvus 会执行 Upsert，自动去重更新！
                await self.index.ainsert_nodes(batch)
                logger.info(f"   -> 成功写入批次 {i // batch_size + 1}")

            logger.info("✅ 全量入库成功！")
        except Exception as e:
            logger.error(f"❌ 入库失败: {e}")
            raise


class MilvusRetrieverService:
    """
    检索服务 (常驻内存，仅初始化一次 Reranker)
    """

    def __init__(self, collection_name: str = "company_knowledge_base"):
        self.index = get_base_index(collection_name)
        logger.info("⏳ 正在加载 BGE-Reranker 模型至显存...")
        self.reranker = FlagEmbeddingReranker(
            top_n=3,
            model="D:/Environment/model/bge-reranker-v2-m3",
            use_fp16=True
        )
        logger.info("✅ 检索服务初始化完毕！")

    async def retrieve_answer(self, query_str: str, filters_dict: dict = None):
        """
        检索数据库
        :param query_str: 搜索的内容
        :param filters_dict: 按字段过滤
        :return:
        """
        logger.info(f"⚙️ 正在向 Milvus 发起混合检索: {query_str}。 过滤字段: {filters_dict}")
        filters = None
        # 构造元数据过滤器
        if filters_dict:
            # 先把字典里 value 为 None 的键值对剔除掉！
            cleaned_filters = {k: v for k, v in filters_dict.items() if v is not None}

            if cleaned_filters:
                filter_list = [
                    MetadataFilter(key=k, value=v, operator=FilterOperator.IN if k == 'acl' else FilterOperator.EQ)
                    for k, v in cleaned_filters.items()
                ]

                filters = MetadataFilters(
                    filters=filter_list,
                    condition=FilterCondition.AND
                )

        # 必须显式声明 vector_store_query_mode="hybrid", 否则milvus中的 BM25 搜索不生效
        hybrid_retriever = self.index.as_retriever(
            similarity_top_k=30,
            # similarity_top_k=3,
            vector_store_query_mode="hybrid",
            filters=filters
        )

        # 多路召回与融合(内部使用RRF重排)
        final_nodes = await hybrid_retriever.aretrieve(query_str)

        if not final_nodes:
            logger.warning("⚠️ 检索结果为空！")
            return []

        # 2. Reranker 精排
        query_bundle = QueryBundle(query_str=query_str)
        final_nodes = self.reranker.postprocess_nodes(
            nodes=final_nodes,
            query_bundle=query_bundle
        )

        return await format_milvus_context(final_nodes)


async def format_milvus_context(nodes):
    """
    格式化 Milvus 向量检索结果：统一 Header 风格
    """
    if not nodes:
        return "【向量库检索】: 未找到相关参考资料。"

    context_parts = ["### 📚 向量库参考文档："]

    # 按照分值排序并去重
    seen_ids = set()
    for i, node_with_score in enumerate(nodes, 1):
        node = node_with_score.node
        if node.node_id in seen_ids: continue
        seen_ids.add(node.node_id)

        score = node_with_score.score
        file_name = node.metadata.get('file_name', '未知文件')
        content = node.get_content().strip()

        # 统一 Header 样式
        header = f"--- [来源: {file_name} | 类型: 原始文本块 | 匹配分值: {score:.4f}] ---"
        context_parts.append(f"{header}\n{content}")

    return "\n\n".join(context_parts)
```

## File: `multi_domain_enterprise_project\rag\milvus\milvus_db.py`

```py
import logging
from llama_index.vector_stores.milvus import MilvusVectorStore
from llama_index.vector_stores.milvus.utils import BM25BuiltInFunction
from llama_index.core import StorageContext
from config import settings

logger = logging.getLogger(__name__)


class EnterpriseMilvusStore:
    """
    企业级 Milvus 存储管理器
    负责连接管理、集合创建、以及 LlamaIndex 的 StorageContext 封装
    """

    def __init__(self, collection_name: str = "rag_knowledge_base", dim: int = 1536):
        self.collection_name = collection_name
        self.dim = dim
        self.uri = settings.milvus.uri
        # self.token = settings.milvus.token  # 如果是 Zilliz Cloud 需要 token，本地不需要

    def _init_vector_store(self) -> MilvusVectorStore:
        """
        初始化 Milvus 向量存储对象
        LlamaIndex 的 MilvusVectorStore 会自动处理 Schema 创建
        """
        try:
            vector_store = MilvusVectorStore(
                uri=self.uri,
                # token=self.token,
                collection_name=self.collection_name,
                dim=self.dim,
                overwrite=False,  # ⚠️ 生产环境千万别设为 True，否则重启就清空数据
                # 混合检索参数 (可选，企业级建议开启)
                enable_sparse=True,  # 开启稀疏向量（milvus底层默认使用BM25能力）
                # sparse_embedding_function=BM25BuiltInFunction(),  # 显示使用milvus内置的BM25向量搜索
                hybrid_ranker="RRFRanker",  # 告诉 Milvus 在数据库端直接执行 RRF 融合
                hybrid_ranker_params={"k": 60},  # RRF的默认平滑常数
            )
            logger.info(f"✅ 成功连接 Milvus 集合: {self.collection_name} (Dim={self.dim})")
            return vector_store
        except Exception as e:
            logger.error(f"❌ 连接 Milvus 失败: {e}")
            raise

    def get_storage_context(self):
        """获取 LlamaIndex 的存储上下文"""
        vector_store = self._init_vector_store()
        return StorageContext.from_defaults(vector_store=vector_store)
```

## File: `multi_domain_enterprise_project\rag\milvus\__init__.py`

```py

```

## File: `multi_domain_enterprise_project\tools\mcp_tools.py`

```py
from langchain_mcp_adapters.client import MultiServerMCPClient

dq = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJocnwxfDIiLCJpc3MiOiJodHRwczovL3hpbnl1LmNvbSIsImlhdCI6MTc3NDk2MTE1OSwiZXhwIjoxNzc1NTY1OTU5LCJhdWQiOiJteS1kZXYtc2VydmVyIiwidGVuYW50IjoiaHIiLCJhY2wiOiIxfDIifQ.JLB72JbStZYNDc-WIb2rLvO09BfUSh6WVR4yfyblMnIpQ8qdyp-Qx4YL2dks7YY_v3NkhQPi9ohaCQZUPpDrizL38sbKwhWRiFWWcuzdTOdF9Y22d_3IyjxPkrm3oZxDEn2MEvWMtkEwuQnolK7kaJCvY68GEZ8-P2JeoJxdlPwPWEGCteSA2apy4R7rQ-iGhJQT39lB2f5dUD59IVAw_Ro4hvajmHnfssv0JFXWF5nm20jfDS70Gerf5HdLAC-8YlU4oGqgCH8f_d5MJingb1xyenAfcsxSjJVLszFZb9k3pejk5aGSGAj5JKAzVSw-Y-GTWDExMiU39jyUMhV8aA"


async def finance_mcp_client():
    """可视化图表"""
    mcp_client = MultiServerMCPClient(
        {
            "可视化图表":
                {  # 可视化图表-MCP-Server
                    "transport": "streamable_http",
                    "url": "https://mcp.api-inference.modelscope.net/dfedfd3e16d04b/mcp"
                },
            "文档检索":
                {  # 文档检索
                    "transport": "streamable-http",
                    "url": "http://127.0.0.1:8000/rag-retriever",
                    "headers": {
                        "Authorization": f"Bearer {dq}"
                    }
                },
        },
    )
    return mcp_client


async def document_retriever_mcp_client():
    """企业内部文档检索"""
    mcp_client = MultiServerMCPClient(
        {"文档检索":
            {  # 文档检索
                "transport": "streamable-http",
                "url": "http://127.0.0.1:8000/rag-retriever",
                "headers": {
                    "Authorization": f"Bearer {dq}"
                }
            },
        }
    )
    return mcp_client


async def tech_mcp_client():
    """网络搜索"""
    mcp_client = MultiServerMCPClient(
        {
            "网络搜索":
                {  # 网络搜索
                    "transport": "streamable-http",
                    "url": "https://open.bigmodel.cn/api/mcp-broker/proxy/web-search/mcp?Authorization=163af72ae3d34e2ebb81919e05b5879b.6QoCjMulVygVKHtu"
                },
            "文档检索":
                {  # 文档检索
                    "transport": "streamable-http",
                    "url": "http://127.0.0.1:8000/rag-retriever",
                    "headers": {
                        "Authorization": f"Bearer {dq}"
                    }
                },
        }
    )
    return mcp_client


async def legal_mcp_client():
    """法律法规"""
    mcp_client = MultiServerMCPClient(
        {
            "法务":
                {  # 法务
                    "transport": "streamable-http",
                    "url": "https://mcp.api-inference.modelscope.net/cb5e7d8119b04f/mcp"
                },
            "文档检索":
                {  # 文档检索
                    "transport": "streamable-http",
                    "url": "http://127.0.0.1:8000/rag-retriever",
                    "headers": {
                        "Authorization": f"Bearer {dq}"
                    }
                },
        }
    )
    return mcp_client
```

## File: `multi_domain_enterprise_project\tools\__init__.py`

```py

```

