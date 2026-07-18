# 企业多智能体 RAG 项目量化实验方案

本文档用于把简历中的量化描述落到可复现实验上：

- 意图识别准确率提升 12%
- 多跳推理召回率提升 20%
- 复杂表格信息保留率提升 30%
- 文档解析成本降低 25%

核心原则：不预设结果，不编造数字。每个百分比必须有公开或可复现的数据来源、baseline、指标、运行脚本和原始结果文件支撑。

## 1. 总体口径

### 1.1 项目被测对象

被测系统是当前仓库的主应用：

- 后端：`multi_domain_enterprise_project`
- 前端：`frontend`
- 多智能体调度：`multi_domain_enterprise_project/agent/supervisor_agent.py`
- RAG 入库与检索：`multi_domain_enterprise_project/rag`
- MCP 工具服务：`multi_domain_enterprise_project/mcp_server`

### 1.2 固定环境

默认运行环境：

- Conda 环境：`rag`
- Redis：Docker，本地 `6379`
- Milvus：Docker，本地 `19530`
- Neo4j：Docker，本地 `7687`
- MCP RAG 服务：`python -m multi_domain_enterprise_project.mcp_server.run_mcp`
- FastAPI 主服务：`python -m multi_domain_enterprise_project.main`
- Ollama：本地 `11434`，需要 `qwen3-embedding:4b`

环境检查命令：

```bash
conda run -n rag python -m multi_domain_enterprise_project.healthcheck
```

### 1.3 结果保存约定

后续实现脚本时，所有实验输出统一保存到：

```text
evals/
  data/              # 下载或抽样后的评测数据
  results/           # JSON/CSV 原始结果
  reports/           # Markdown 汇总报告
  routing/           # 意图识别与路由实验脚本
  rag/               # 检索与 GraphRAG 实验脚本
  parsing/           # 文档解析实验脚本
```

每个实验至少输出：

- `config.json`：数据集、样本量、baseline、模型、参数
- `raw_predictions.jsonl`：逐条预测或检索结果
- `metrics.json`：聚合指标
- `report.md`：简历可引用结论和注意事项

## 2. 实验 A：意图识别与动态路由

### 2.1 要证明的简历点

建议写法：

> 基于 LangGraph 构建 Supervisor 多智能体路由，在公开 intent/OOS 基准与企业自建路由集上，相比单层 LLM 路由准确率提升 12%。

### 2.2 数据集

采用公开基准 + 企业场景补充集：

1. CLINC150 抽样集
   - 用途：验证 intent classification 与 out-of-scope 识别。
   - 公开依据：UCI 页面说明 CLINC150 有 150 个 in-domain intent 类，主要用于评估 out-of-domain performance。
   - 推荐样本量：200 条。

2. 企业路由集
   - 用途：贴合本项目 HR、财务、法务、技术、多领域、需追问场景。
   - 推荐样本量：120 条。
   - 类别分布：
     - HR：20
     - Finance：20
     - Legal：20
     - Tech：20
     - Multi-domain：20
     - Need-clarification/OOS：20

合计约 320 条。这个规模足够避免样本过少导致偶然性，也不会把评测做成学术大工程。

### 2.3 基线

1. `keyword_router`
   - 关键词和规则路由。
   - 代表传统工程规则方案。

2. `single_llm_router`
   - 单次 LLM prompt 直接选择 agent。
   - 不调用 `get_sub_agent_list`，不使用 Human-in-the-Loop。

3. `langgraph_supervisor`
   - 当前项目方案。
   - 使用 Supervisor + tool calling + Human-in-the-Loop。

### 2.4 指标

- `route_accuracy`：完全命中目标 agent 集合的比例。
- `macro_f1`：多类别宏平均 F1。
- `clarification_accuracy`：需追问/OOS 样本是否正确触发追问。
- `multi_domain_f1`：多领域任务的 agent 集合匹配 F1。

### 2.5 提升率公式

```text
relative_improvement = (our_metric - baseline_metric) / baseline_metric
absolute_gain = our_metric - baseline_metric
```

简历中写“提升 12%”时，优先使用相对提升；报告中必须同时列出绝对提升。

## 3. 实验 B：Milvus + Neo4j 混合 RAG

### 3.1 要证明的简历点

建议写法：

> 构建 Milvus + Neo4j 双路混合 RAG，在 MultiHop-RAG 多跳检索任务上，相比 vector-only Recall@10 提升 20%。

### 3.2 数据集

主数据集：MultiHop-RAG。

- 用途：评估跨文档多跳检索与 RAG 推理。
- 公开依据：官方仓库说明它包含 2556 个 queries，每个 query 的 evidence 分布在 2 到 4 个文档中，并包含 metadata，贴近真实 RAG 应用。
- 推荐样本量：200 个 query。

补充检索基准：BEIR 小样本。

- 用途：证明检索指标采用信息检索社区常见口径。
- 公开依据：BEIR 是 heterogeneous IR benchmark，并提供统一评估框架。
- 推荐样本量：可选 1 个子集的 100 个 query，仅用于 sanity check，不作为简历主数字。

### 3.3 基线

1. `vector_only`
   - 只使用 Milvus。
   - 对应 `mode=milvus`。

2. `graph_only`
   - 只使用 Neo4j GraphRAG。
   - 对应 `mode=graph`。

3. `hybrid_mg`
   - Milvus + Neo4j 双路检索。
   - 对应 `mode=mg`。

4. `hybrid_mg_rerank`
   - 双路检索 + reranker。
   - 如果本地 reranker 环境稳定，再作为增强版本。

### 3.4 指标

检索指标：

- `Recall@5`
- `Recall@10`
- `MRR`
- `nDCG@10`

RAG 指标：

- `context_precision`
- `context_recall`
- `faithfulness`
- `response_relevancy`

RAG 指标可用 RAGAS。公开依据：RAGAS 官方列出了 RAG 评测常用指标，包括 Context Precision、Context Recall、Response Relevancy、Faithfulness。

### 3.5 提升率公式

主口径：

```text
relative_recall_lift = (hybrid_mg_recall_at_10 - vector_only_recall_at_10) / vector_only_recall_at_10
```

简历中的“多跳推理召回率提升 20%”只允许使用 MultiHop-RAG 的 `Recall@10` 或 `context_recall` 作为主指标，不能混用多个指标挑最高值。

## 4. 实验 C：智能文档解析路由

### 4.1 要证明的简历点

建议写法：

> 设计复杂文档解析路由器，在 OmniDocBench/PubTables 子集上，相比固定本地解析表格信息保留率提升 30%；相比全量云解析，解析成本降低 25%。

### 4.2 数据集

1. OmniDocBench 抽样集
   - 用途：评估真实 PDF 文档解析，包括版面、表格、公式、OCR 等维度。
   - 公开依据：官方仓库说明它面向 diverse document parsing，支持 end-to-end、layout detection、table recognition、formula recognition、text OCR，并包含 TEDS 等指标。
   - 推荐样本量：40 页。

2. PubTables-1M 抽样集
   - 用途：专门评估表格结构识别和表头/单元格保留。
   - 公开依据：Microsoft Research 页面说明 PubTables-1M 包含 nearly one million tables，并支持 table detection、structure recognition、functional analysis。
   - 推荐样本量：20 个表格页。

合计约 60 个页面级样本。文档解析成本高，60 个高质量复杂样本比大量低质量样本更适合这个项目阶段。

### 4.3 基线

1. `local_fast_only`
   - PDF 固定 PyMuPDF。
   - Office/text 固定 MarkItDown。
   - 不调用 Qwen-VL 或 LlamaParse。

2. `cloud_accurate_only`
   - 所有复杂格式固定 LlamaParse。
   - 作为高质量但高成本 baseline。

3. `auto_router`
   - 当前 `DocumentParserRouter(mode="auto")`。
   - 根据文件类型和复杂度选择 PyMuPDF、Qwen2.5-VL、LlamaParse、MarkItDown。

### 4.4 指标

质量指标：

- `table_teds`
- `cell_recall`
- `header_recall`
- `numeric_value_recall`
- `normalized_edit_distance`

成本与性能指标：

- `parse_latency_seconds`
- `cloud_call_rate`
- `estimated_cost`
- `failure_rate`

`estimated_cost` 初期按调用次数和配置单价估算；如果没有稳定 API 账单，不把估算成本写成真实财务成本。

### 4.5 提升率公式

信息保留率：

```text
table_retention_lift = (auto_router_table_metric - local_fast_only_table_metric) / local_fast_only_table_metric
```

解析成本降低：

```text
cost_reduction = (cloud_accurate_only_cost - auto_router_cost) / cloud_accurate_only_cost
```

简历中的“复杂表格信息保留率提升 30%”优先使用 `cell_recall` 或 `table_teds`，二选一作为主指标；不能在报告后期临时改指标。

## 5. 实验执行顺序

后续按以下顺序逐项完成：

1. 环境检查
   - 跑 `healthcheck`。
   - 确认 Redis、Milvus、Neo4j、MCP、Ollama 可用。

2. 路由实验
   - 先实现无外部入库依赖的路由评测。
   - 产出第一个可引用数字。

3. RAG 检索实验
   - 下载/抽样 MultiHop-RAG。
   - 分别跑 Milvus、Neo4j、Hybrid。
   - 产出 Recall@10 主数字。

4. 文档解析实验
   - 准备 OmniDocBench/PubTables 子集。
   - 跑 local-only、cloud-only、auto-router。
   - 产出表格保留率和成本数字。

5. 汇总报告
   - 生成 `evals/reports/final_resume_metrics.md`。
   - 明确哪些数字可写简历，哪些只能作为内部实验结论。

## 6. 验收标准

每个数字必须满足：

- 有可定位数据集来源。
- 有固定样本量和抽样规则。
- 有 baseline。
- 有逐条原始预测或检索结果。
- 有聚合指标 JSON。
- 有一条命令可复跑。
- 报告中同时给出相对提升和绝对提升。

如果结果没有达到目标百分比，不修改原始数字；改写简历表述为真实结果，或继续优化系统后重跑。

## 7. 公开资料来源

- CLINC150: https://archive.ics.uci.edu/dataset/570/clinc150
- MultiHop-RAG: https://github.com/yixuantt/MultiHop-RAG
- RAGAS 指标：https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/
- BEIR: https://github.com/beir-cellar/beir
- OmniDocBench: https://github.com/opendatalab/OmniDocBench
- PubTables-1M: https://www.microsoft.com/en-us/research/publication/pubtables-1m/

## 8. 已完成结果快照（2026-07-07）

本节记录当前已经跑通的量化证据，后续如继续优化，以对应 `evals/reports/` 下的最新报告为准。

### 8.1 意图识别与动态路由

- 报告：`evals/reports/routing_intent_evaluation.md`
- 企业域子集：`single_llm_router` 80.83%，`langgraph_supervisor` 96.67%
- 绝对提升：+15.84pp
- 相对提升：+19.60%
- 判定：可以支撑“意图识别/路由准确率提升 12%+”。

### 8.2 MultiHop-RAG 多跳检索

- 无监督报告：`evals/reports/multihop_rag_chunk_rerank_evaluation.md`
- 监督排序报告：`evals/reports/multihop_rag_lambdamart_evaluation.md`
- 公开样本：MultiHop-RAG 2255 条可评估 query
- 无监督 chunk + metadata/source coverage rerank：Recall@10 从 79.84% 到 90.82%，相对提升 13.75%
- Supervised LambdaMART rerank（train 1300 / dev 200 / holdout 755）：holdout Recall@10 从 78.97% 到 96.61%，相对提升 22.34%
- 鲁棒性补充（train 1500 / holdout 755）：holdout Recall@10 从 78.97% 到 97.11%，相对提升 22.97%
- 判定：可以支撑“多跳检索 Recall@10 提升 20%+”，但必须写清楚是“chunk-level candidate generation + LambdaMART rerank”的监督排序版本；无监督 GraphRAG/rerank 版本只能写 13.75%。

### 8.3 文档解析与复杂表格保留

- 控制实验报告：`evals/reports/document_parsing_evaluation.md`
- PubTables 公开实验报告：`evals/reports/pubtables_document_parsing_evaluation.md`
- 控制样本：30 个 native PDF / scanned PDF / XLSX，auto-router 相比 local-fast-only 表格保留分数相对提升 49.99%，云调用次数降低 100%
- PubTables-1M OTSL v1.1 `test` split：50 个公开表格样本，image-only PDF 文本基线 table retention 为 0，router-auto PDF 为 86.94%，direct image OCR 为 89.52%
- 判定：可以支撑“复杂表格信息保留率提升 30%+”，但公开 PubTables 结果应写绝对提升或保留分数，不写相对倍数。
