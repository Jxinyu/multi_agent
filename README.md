# multi-agent RAG

企业多智能体 + RAG + MCP 示例项目，已拆分为 React 前端和 FastAPI 后端。

## 架构

主工程在 `multi_domain_enterprise_project`：

1. `main.py` 提供 FastAPI + SSE 聊天 API，并托管前端构建产物。
2. `agent/supervisor_agent.py` 定义 LangGraph 调度图。
3. `agent/*_agent.py` 是 HR、财务、法务、技术领域专家。
4. `rag/` 负责文档解析、切片、Milvus/Neo4j 入库和检索。
5. `mcp_server/` 将 RAG 检索暴露为 FastMCP 工具。

`frontend` 是独立 React 前端。`chain_graph` 和 `algorithm` 是实验/练习代码，不是主服务入口。

## 前端目录

- `frontend/src/api`：后端 API 与 SSE 流式解析。
- `frontend/src/hooks`：聊天会话状态、停止请求、重置会话、历史会话持久化。
- `frontend/src/components`：Header、消息列表、输入区、会话侧栏等 UI 组件。
- `frontend/src/types.ts`：前端共享类型。

当前前端能力：

- React + Vite + TypeScript。
- SSE 流式读取 `/api/chat`。
- 最近会话侧栏，使用 `localStorage` 持久化。
- 引用来源折叠/展开。
- 请求中可停止，支持新会话重置。
- 支持上传图片、PDF、Office 文档和文本类附件，后端复用 `DocumentParserRouter` 自动解析后注入对话上下文。
- 当前视觉风格偏内部工作台：低饱和配色、紧凑布局、弱装饰。

## 本地依赖

需要先启动：

- Redis
- Milvus
- Neo4j
- Ollama，并拉取 `qwen3-embedding:4b`
- 可选：本地 VLM 模型 `qwen2.5vl:3b`
- 可选：本地 reranker 模型，默认路径 `D:/Environment/model/bge-reranker-v2-m3`

安装 Python 依赖：

```bash
pip install -r requirements.txt
```

安装前端依赖：

```bash
cd frontend
npm install
```

## 配置

复制 `.env.example` 为 `.env`，填入本地密钥和服务地址。仓库内 `config/config.yaml` 只保留非敏感默认值；真实密钥必须放在 `.env`。

常用变量：

- `QWEN_API_KEY`
- `LLAMA_PARSE_API_KEY`
- `REDIS_URL`
- `MILVUS_URI`
- `NEO4J_URL`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`
- `MCP_RAG_URL`
- `MCP_DOCUMENT_TOKEN`

## 启动

启动 RAG MCP 服务：

```bash
python -m multi_domain_enterprise_project.mcp_server.run_mcp
```

启动聊天 API：

```bash
python -m multi_domain_enterprise_project.main
```

默认使用单进程启动，避免 Windows 下 reload 子进程残留导致端口仍挂在旧代码上。需要自动重载时再设置 `UVICORN_RELOAD=1`。

浏览器打开：

```text
http://127.0.0.1:8080
```

前端开发模式：

```bash
cd frontend
npm run dev
```

默认代理到 `http://127.0.0.1:8080/api`。

生产构建：

```bash
cd frontend
npm run build
```

后端会优先托管 `frontend/dist`。

## 检查

本地服务健康检查：

```bash
python -m multi_domain_enterprise_project.healthcheck
```

只检查部分服务：

```bash
python -m multi_domain_enterprise_project.healthcheck --only redis milvus ollama
```

后端语法检查：

```bash
python -m compileall config multi_domain_enterprise_project
```

前端检查：

```bash
cd frontend
npm run typecheck
npm run build
```

评估脚本：

```bash
python -m multi_domain_enterprise_project.tests.eval_supervisor.eval_supervisor_llm
python -m multi_domain_enterprise_project.tests.eval_rag_recall.eval_rag_recall_llm
```
