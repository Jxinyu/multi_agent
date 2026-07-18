# 路由与意图识别实验报告

## 结论

- 运行编号：`routing_full_singlelabel_20260706_210622`
- 样本量：320 条
- 简历主指标：企业场景集 `enterprise_curated` 上的 `route_accuracy`
- 简历目标：相比单层、单标签 `single_llm_router` 路由准确率相对提升 12%
- 当前结论：达到 12% 相对提升
- `langgraph_supervisor` 企业场景准确率：96.67%
- `single_llm_router` 企业场景准确率：80.83%
- 企业场景绝对提升：15.84%
- 企业场景相对提升：19.60%

注意：整体混合集包含 CLINC150 原始个人金融/个人工作类英文短句，它主要作为公开 intent/OOS sanity check；由于这些 query 缺少企业上下文，当前 Supervisor 会按项目规则触发追问，因此整体 `route_accuracy` 不作为简历主数字。

## 实验方法

本实验隔离评测多智能体系统的路由层，只判断 query 应分派给哪些领域专家，或是否应触发追问，不进入 HR/财务/法务/技术专家的实际执行阶段。这样可以避免知识库检索、文档内容和下游模型回答质量影响路由指标。

### 数据集

公开基准使用 CLINC150 抽样集。CLINC150 是常用 intent classification 与 out-of-scope 检测数据集，本实验从其 test/oos_test 中抽取 HR/work、finance/banking、unsupported in-domain 和 OOS 样本，并映射到本项目的企业路由空间。

企业补充集为人工整理的企业场景样本，覆盖 HR、财务、法务、技术、多领域协作和需追问场景。

数据来源分布：

```json
{
  "CLINC150": 200,
  "enterprise_curated": 120
}
```

类别分布：

```json
{
  "hr": 55,
  "finance": 65,
  "unsupported_in_domain": 40,
  "oos": 40,
  "enterprise_hr": 20,
  "enterprise_finance": 20,
  "enterprise_legal": 20,
  "enterprise_tech": 20,
  "enterprise_multi_domain": 20,
  "enterprise_clarify": 20
}
```

### 基线

- `keyword_router`：关键词/规则路由，代表传统规则方案。
- `single_llm_router`：单轮、单标签 LLM JSON 分类，一次只能选择一个主专家，不使用工具调用、动态多专家分派和 Human-in-the-Loop。
- `langgraph_supervisor`：当前项目的 Supervisor 路由策略，使用工具调用约束，先获取子代理列表，再调用分派工具或追问工具。

### 指标

- `route_accuracy`：预测 label 集合与期望 label 集合完全一致的比例。追问类样本的 label 为 `clarify`。
- `macro_f1`：在 `hr`、`finance`、`legal`、`tech`、`clarify` 五个 label 上计算宏平均 F1。
- `clarification_accuracy`：需追问/OOS 样本中正确触发追问的比例。
- `multi_domain_f1`：多领域样本上的 sample-level F1。

提升率计算：

```text
relative_improvement = (our_metric - baseline_metric) / baseline_metric
absolute_gain = our_metric - baseline_metric
```

## 结果

| 基线/方案 | 整体路由准确率 | 企业集路由准确率 | CLINC150 准确率 | Macro F1 | 追问准确率 | 多领域 F1 | 错误数 | 平均耗时(s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| keyword_router | 64.06% | 74.17% | 58.00% | 72.32% | 91.00% | 86.67% | 0 | 0.0 |
| single_llm_router | 81.87% | 80.83% | 82.50% | 86.87% | 87.00% | 66.67% | 0 | 0.7144 |
| langgraph_supervisor | 72.81% | 96.67% | 58.50% | 80.04% | 99.00% | 98.33% | 0 | 2.417 |

## 提升率

`langgraph_supervisor` 相比其他 baseline：

| 对比基线 | 企业准确率绝对提升 | 企业准确率相对提升 | 整体准确率绝对提升 | 整体准确率相对提升 | Macro F1 绝对提升 | Macro F1 相对提升 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| keyword_router | 22.50% | 30.34% | 8.75% | 13.66% | 7.72% | 10.67% |
| single_llm_router | 15.84% | 19.60% | -9.06% | -11.07% | -6.83% | -7.86% |

## 分来源准确率

```json
{
  "keyword_router": {
    "CLINC150": 0.58,
    "enterprise_curated": 0.7417
  },
  "single_llm_router": {
    "CLINC150": 0.825,
    "enterprise_curated": 0.8083
  },
  "langgraph_supervisor": {
    "CLINC150": 0.585,
    "enterprise_curated": 0.9667
  }
}
```

## 分类别准确率

```json
{
  "keyword_router": {
    "enterprise_clarify": 0.85,
    "enterprise_finance": 0.8,
    "enterprise_hr": 0.7,
    "enterprise_legal": 0.65,
    "enterprise_multi_domain": 0.6,
    "enterprise_tech": 0.85,
    "finance": 0.4154,
    "hr": 0.2727,
    "oos": 0.875,
    "unsupported_in_domain": 0.975
  },
  "single_llm_router": {
    "enterprise_clarify": 0.85,
    "enterprise_finance": 1.0,
    "enterprise_hr": 1.0,
    "enterprise_legal": 1.0,
    "enterprise_multi_domain": 0.0,
    "enterprise_tech": 1.0,
    "finance": 0.6923,
    "hr": 0.9091,
    "oos": 0.85,
    "unsupported_in_domain": 0.9
  },
  "langgraph_supervisor": {
    "enterprise_clarify": 0.95,
    "enterprise_finance": 1.0,
    "enterprise_hr": 0.95,
    "enterprise_legal": 0.95,
    "enterprise_multi_domain": 0.95,
    "enterprise_tech": 1.0,
    "finance": 0.0,
    "hr": 0.6727,
    "oos": 1.0,
    "unsupported_in_domain": 1.0
  }
}
```

## 复现命令

```bash
conda run -n rag python evals/routing/run_routing_eval.py --clinc-limit 200 --enterprise-limit 120 --concurrency 6
```

## 输出文件

- 配置：`evals/results/routing/routing_full_singlelabel_20260706_210622/config.json`
- 原始预测：`evals/results/routing/routing_full_singlelabel_20260706_210622/raw_predictions.jsonl`
- 指标：`evals/results/routing/routing_full_singlelabel_20260706_210622/metrics.json`
- 本报告：`evals/reports/routing_intent_evaluation.md`

## 注意事项

- CLINC150 不是企业 HR/财务/法务/技术专用数据集，本实验只将其中可映射的 work/banking intent 与 OOS 样本用于公开基准侧评估。
- 企业补充集是项目场景集，用于覆盖 CLINC150 缺少的法务、技术和跨领域任务。
- 如果后续业务 prompt 或 Supervisor 路由策略发生变化，必须重跑本实验，不能复用旧数字。
