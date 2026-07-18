# multi-agent RAG

企业多智能体 + RAG + MCP 示例项目，已拆分为 React 前端和 FastAPI 后端。

## 项目介绍

本项目面向企业 HR、财务、法务、技术等多领域知识问答场景，采用 LangGraph 分层 Supervisor 架构进行意图识别、动态路由和跨域任务编排；知识库侧结合 Milvus 向量检索、Neo4j 知识图谱和重排序策略；文档解析侧通过路由器在 PyMuPDF、MarkItDown、RapidOCR、Qwen2.5-VL、LlamaParse 等解析方式之间动态选择。

核心目标：

- 减少跨领域问题被错误路由到单一 agent。
- 提升多跳问题的证据文档召回率。
- 降低扫描件、图片表格和复杂 Office 文档解析时的字段丢失。
- 通过 FastAPI SSE、MCP、JWT、多租户字段和状态持久化支撑企业部署形态。

## 架构

主工程在 `multi_domain_enterprise_project`：

1. `main.py` 提供 FastAPI + SSE 聊天 API，并托管前端构建产物。
2. `agent/supervisor_agent.py` 定义 LangGraph 调度图。
3. `agent/*_agent.py` 是 HR、财务、法务、技术领域专家。
4. `rag/` 负责文档解析、切片、Milvus/Neo4j 入库和检索。
5. `mcp_server/` 将 RAG 检索暴露为 FastMCP 工具。

`frontend` 是独立 React 前端。`chain_graph` 和 `algorithm` 是实验/练习代码，不是主服务入口。

## 技术栈

- 后端：FastAPI、LangChain、LangGraph、LlamaIndex、FastMCP
- 检索：Milvus、Neo4j、BM25、LambdaMART rerank
- 文档解析：PyMuPDF、MarkItDown、RapidOCR、Qwen2.5-VL、LlamaParse
- 状态与权限：Redis、JWT、多租户 metadata/ACL
- 前端：React、Vite、TypeScript、SSE 流式响应

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
- `MCP_PUBLIC_KEY_PATH`
- `MCP_PRIVATE_KEY_PATH`

MCP JWT 签名密钥不要提交到 Git。可以在本地生成：

```bash
openssl genrsa -out multi_domain_enterprise_project/mcp_server/private_key 2048
openssl rsa -in multi_domain_enterprise_project/mcp_server/private_key -pubout -out multi_domain_enterprise_project/mcp_server/public_key
```

如果密钥放在其他目录，通过 `.env` 中的 `MCP_PRIVATE_KEY_PATH` 和 `MCP_PUBLIC_KEY_PATH` 指定。

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

## 量化实验

项目级评估脚本和报告在 `evals/` 下。`evals/data/` 与 `evals/results/` 是下载数据、embedding 缓存和原始实验输出，不入库；保留入库的是可复现实验脚本和中文报告。

简历可引用口径以 `evals/reports/final_resume_metrics.md` 为准：

| 模块 | 实验基准 | 当前结果 |
| --- | --- | --- |
| 意图识别与动态路由 | 单层 LLM 路由 | 企业场景路由准确率相对提升 19.60% |
| 多跳 RAG 检索 | 文档级向量检索 | MultiHop-RAG holdout Recall@10 相对提升 22.34% |
| 复杂表格解析 | 固定本地快速解析 | 控制样本表格保留分数相对提升 49.99% |
| 解析成本 | 固定云解析 | 云解析调用次数从 30 次降至 0 次 |

数据来源：

- 路由：CLINC150/OOS 公开数据 + 项目自建企业路由样本。
- RAG：MultiHop-RAG 官方 `MultiHopRAG.json` 与 `corpus.json`。
- 文档解析：脚本生成控制样本 + PubTables-1M OTSL 公开 test split 抽样。

复现命令：

```bash
python evals/routing/run_routing_eval.py --clinc-limit 200 --enterprise-limit 120 --concurrency 6
python evals/rag/run_multihop_lambdamart_eval.py --query-limit 2556 --train-size 1300 --dev-size 200 --candidate-top-k 100 --chunk-top-k 400 --num-leaves 63 --n-estimators 650
python evals/parsing/run_document_parsing_eval.py --sample-limit 30
python evals/parsing/run_pubtables_parsing_eval.py --limit 50 --run-id pubtables_public_50_20260707 --parser-timeout-s 90
```
