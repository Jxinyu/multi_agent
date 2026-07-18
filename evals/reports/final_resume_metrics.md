# 最终简历量化指标汇总

日期：2026-07-07

本文档是简历可引用数字的统一口径。使用这些数字时，必须同时保留对应的实验范围和限制说明。

## 0. 数据来源总览

| 实验 | 数据从哪来 | 金标从哪来 | 本地证据 |
| --- | --- | --- | --- |
| 意图识别与动态路由 | CLINC150/OOS 公开数据 + 项目自建企业路由样本 | CLINC150 原始 intent；企业样本由脚本手写标注期望 agent | `evals/data/routing/clinc150_data_full.json`、`evals/data/routing/routing_cases.jsonl` |
| 多跳 RAG 检索 | MultiHop-RAG 官方 `MultiHopRAG.json` + `corpus.json` | `MultiHopRAG.json` 中每条 query 的 `evidence_list.title` | `evals/data/rag/MultiHopRAG.json`、`evals/data/rag/corpus.json` |
| 复杂表格解析（控制实验） | 项目脚本生成的 native PDF、扫描 PDF、XLSX 样本 | 生成样本时同步写入的表头、单元格、数值字段 | `evals/data/parsing/controlled_manifest.json` |
| 复杂表格解析（公开补充） | Hugging Face `docling-project/PubTables-1M_OTSL-v1.1` 的 test split | PubTables 样本自带 cell 文本和表格结构标注 | `evals/data/parsing/pubtables/manifest_test_50.json` |
| 解析成本 | 同一批控制解析样本 | 不涉及答案金标，统计云解析调用次数 | `evals/results/parsing/parsing_full_20260706_220325/metrics.json` |

外部公开来源：

- CLINC150/OOS：`https://github.com/clinc/oos-eval`
- MultiHop-RAG：`https://github.com/yixuantt/MultiHop-RAG`
- PubTables-1M：`https://www.microsoft.com/en-us/research/publication/pubtables-1m/`
- PubTables OTSL 数据集：`https://huggingface.co/datasets/docling-project/PubTables-1M_OTSL-v1.1`

## 1. 意图识别与动态路由

简历可写：

> 基于 LangGraph 构建企业多智能体 Supervisor 路由，覆盖 HR、财务、法务、技术等场景，相比单层 LLM 路由在企业场景集上的准确率相对提升 19.60%。

证据：

- 报告：`evals/reports/routing_intent_evaluation.md`
- 运行编号：`routing_full_singlelabel_20260706_210622`
- 数据集：共 320 条路由样本；简历主数字使用其中 120 条企业场景样本
- 公开数据来源：脚本从 CLINC150/OOS 的 `data_full.json` 下载公开 intent 数据，并缓存到 `evals/data/routing/clinc150_data_full.json`
- 企业数据来源：`evals/routing/run_routing_eval.py::build_enterprise_cases()` 手写构造 120 条企业场景，覆盖 HR、财务、法务、技术、跨域和追问类问题；生成后的样本写入 `evals/data/routing/routing_cases.jsonl`
- 金标来源：公开样本使用 CLINC150 原始 intent 映射；企业样本在构造时同步写入期望路由 agent
- 基线：`single_llm_router`
- 当前方案：`langgraph_supervisor`

验证方法：

- 怎么测：将每条 query 的期望路由标签与系统输出标签做集合完全匹配，统计企业场景 `route_accuracy`。
- 为什么这样测：该实验只评估路由层，避免下游知识库召回和回答生成质量干扰意图识别结果。
- 基准是什么：`single_llm_router`，即单轮 LLM 直接分类，不使用分层 Supervisor、工具调用和 Human-in-the-Loop 追问。

结果：

| 指标 | 基线 | 当前方案 | 绝对提升 | 相对提升 |
| --- | ---: | ---: | ---: | ---: |
| 企业场景路由准确率 | 80.83% | 96.67% | +15.84pp | +19.60% |

判定：可以支撑原始 `+12%` 的简历表述。

## 2. 多跳 RAG 检索

简历可写：

> 将 MultiHop-RAG 检索从文档级向量检索升级为 chunk 级候选召回 + LambdaMART 重排序，在严格 holdout 上将 Recall@10 相对提升 22.34%。

证据：

- 报告：`evals/reports/multihop_rag_lambdamart_evaluation.md`
- 脚本：`evals/rag/run_multihop_lambdamart_eval.py`
- 运行编号：`rag_lambdamart_enriched_train1300_dev200_20260707`
- 数据来源：MultiHop-RAG 官方数据，脚本下载 `MultiHopRAG.json` 和 `corpus.json`，本地缓存到 `evals/data/rag/MultiHopRAG.json`、`evals/data/rag/corpus.json`
- 金标来源：`MultiHopRAG.json` 中每条 query 的 `evidence_list.title`，即回答该问题需要召回的证据文档标题
- 数据规模：跳过 `null_query` 后共 2255 条可评估 query
- 划分：train 1300 / dev 200 / holdout 755
- 基线：`vector_only`
- 当前方案：`lambdamart_source_coverage`
- 说明：金标证据只在训练集内作为排序标签使用，holdout 只用于最终评分。

验证方法：

- 怎么测：在 MultiHop-RAG 官方数据上检索 top-10 文档，计算返回文档标题命中金标证据标题的 `Recall@10`。
- 为什么这样测：MultiHop-RAG 的证据分布在 2-4 篇文档中，适合验证多跳检索是否能召回完整上下文；holdout 不参与训练，用于证明泛化。
- 基准是什么：`vector_only`，即只使用文档级向量检索；当前方案在同一候选数据上加入 chunk 级召回、BM25 和 LambdaMART 重排序。

结果：

| 指标 | 基线 | 当前方案 | 绝对提升 | 相对提升 |
| --- | ---: | ---: | ---: | ---: |
| Holdout Recall@10 | 78.97% | 96.61% | +17.64pp | +22.34% |

鲁棒性补充：

| 运行编号 | Train | Dev | Holdout | 基线 Recall@10 | 当前方案 Recall@10 | 相对提升 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `rag_lambdamart_enriched_train1300_dev200_20260707` | 1300 | 200 | 755 | 78.97% | 96.61% | 22.34% |
| `rag_lambdamart_enriched_1500_20260707` | 1500 | 0 | 755 | 78.97% | 97.11% | 22.97% |

判定：可以支撑原始 `+20%` 的简历表述，但必须限定为监督式 LambdaMART 重排序版本。无监督 chunk/source coverage 版本只能支撑 `+13.75%`。

## 3. 复杂表格解析

简历可写：

> 设计文档解析路由器，识别扫描件和图像表格并路由到本地 OCR，在控制样本上将表格保留分数相对提升 49.99%，并用 PubTables-1M 公开样本补充验证。

证据：

- 控制实验报告：`evals/reports/document_parsing_evaluation.md`
- PubTables 公开实验报告：`evals/reports/pubtables_document_parsing_evaluation.md`
- 控制实验运行编号：`parsing_full_20260706_220325`
- PubTables 运行编号：`pubtables_public_50_20260707`
- 控制样本来源：`evals/parsing/run_document_parsing_eval.py::generate_samples()` 生成 native PDF、扫描 PDF、XLSX 三类样本；金标来自脚本生成表格时同步写入的表头、单元格、数值字段
- 公开样本来源：`evals/parsing/run_pubtables_parsing_eval.py` 从 Hugging Face `docling-project/PubTables-1M_OTSL-v1.1` 的 test split 流式抽取 50 个表格样本，并缓存图片、PDF 和 gold cell 标注
- 公开样本用途：PubTables 只作为公开数据补充验证，不是 PubTables 官方排行榜分数

验证方法：

- 怎么测：控制样本用预设表头、单元格、数值作为金标，计算 `table_retention_score`；PubTables 公开样本用数据集自带 cell 文本作为金标，计算单元格、数值和表头召回。
- 为什么这样测：文档解析的核心风险是扫描件和复杂表格丢字段，因此用 cell 级召回比只看全文字符数更贴近企业表格解析场景。
- 基准是什么：控制实验基线为 `local_fast_only`，即固定走 PyMuPDF/MarkItDown；PubTables 基线为 `pymupdf_text_only_pdf`，即 image-only PDF 上的纯文本抽取路径。

控制样本结果：

| 指标 | 基线 `local_fast_only` | 当前方案 `auto_router` | 相对提升 |
| --- | ---: | ---: | ---: |
| 表格保留分数 | 66.67% | 100.00% | 49.99% |

PubTables-1M 公开样本验证：

| 解析器 | 单元格召回 | 数值召回 | 表头召回 | 表格保留分数 |
| --- | ---: | ---: | ---: | ---: |
| `pymupdf_text_only_pdf` | 0.00% | 0.00% | 0.00% | 0.00% |
| `router_auto_pdf` | 87.38% | 87.53% | 84.23% | 86.94% |
| `rapidocr_direct_image` | 90.90% | 90.43% | 82.49% | 89.52% |

判定：可以支撑原始 `+30%` 的简历表述。PubTables 的文本抽取基线为 0，因此公开样本部分建议写“保留分数达到 86.94%”或“绝对提升 86.94pp”，不要写相对倍数。

## 4. 解析成本降低

简历可写：

> 通过将扫描 PDF 和图片路由到本地 OCR，减少不必要的云解析调用；在控制实验中云解析调用从 30 次降至 0 次。

证据：

- 报告：`evals/reports/document_parsing_evaluation.md`
- 运行编号：`parsing_full_20260706_220325`
- 数据来源：同复杂表格解析控制样本，即 `evals/data/parsing/controlled_manifest.json`
- 成本代理指标：云解析器调用次数

验证方法：

- 怎么测：统计同一批文档在不同解析策略下触发 LlamaParse 等云解析器的调用次数。
- 为什么这样测：当前没有真实账单数据，因此用云调用次数作为可复现的成本代理指标，避免把估算成本写成真实财务成本。
- 基准是什么：`cloud_accurate_only`，即复杂样本固定走云解析；当前方案为 `auto_router`，扫描件和图片优先路由到本地 OCR。

结果：

| 指标 | 云解析基线 | 自动路由 | 降低比例 |
| --- | ---: | ---: | ---: |
| 云解析调用次数 | 30 | 0 | 100.00% |

判定：当成本定义为云调用次数时，可以支撑原始 `-25%` 的简历表述。除非后续加入真实账单数据，否则不要写成真实财务成本。

## 面试回答速记

- 路由数据：公开 CLINC150/OOS 用来补充通用 intent，主指标来自 120 条手写企业场景集。
- RAG 数据：公开 MultiHop-RAG，答案金标是官方 `evidence_list` 里的证据标题。
- 解析数据：控制实验样本是脚本生成的可复现金标；公开补充是 PubTables-1M OTSL test split 抽样 50 条。
- 成本数据：不是账单金额，是同一批控制样本下的云解析调用次数代理指标。

## 推荐简历写法

> 面向企业 HR、财务、法务、技术等多领域场景，构建 LangGraph 分层 Supervisor 多智能体 RAG 系统；在 120 条企业路由集上相较单层 LLM 路由准确率提升 19.60%，在 MultiHop-RAG 755 条严格 holdout 上通过 chunk 级候选生成 + LambdaMART 重排序将 Recall@10 从 78.97% 提升至 96.61%（+22.34%），并在文档解析路由中结合 PyMuPDF/MarkItDown/RapidOCR/LlamaParse，使控制样本表格保留分数提升 49.99%，PubTables-1M 50 个公开表格样本表格保留分数达 86.94%，云解析调用从 30 次降至 0 次。

## 复现命令

```bash
conda run -n rag python evals/routing/run_routing_eval.py --clinc-limit 200 --enterprise-limit 120 --concurrency 6
conda run -n rag python evals/rag/run_multihop_lambdamart_eval.py --query-limit 2556 --train-size 1300 --dev-size 200 --candidate-top-k 100 --chunk-top-k 400 --num-leaves 63 --n-estimators 650
conda run -n rag python evals/parsing/run_document_parsing_eval.py --sample-limit 30
conda run -n rag python evals/parsing/run_pubtables_parsing_eval.py --limit 50 --run-id pubtables_public_50_20260707 --parser-timeout-s 90
```
