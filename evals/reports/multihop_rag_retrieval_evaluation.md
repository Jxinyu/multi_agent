# MultiHop-RAG 检索实验报告

## 结论

- 运行编号：`rag_multihop_adaptive_500_20260706`
- 样本量：500 个 query
- Corpus：MultiHop-RAG 官方 corpus，609 篇文档
- 主指标：`Recall@10`
- 简历目标：GraphRAG/rerank 相比 vector-only Recall@10 相对提升 20%
- 当前结论：未达到 20% 相对提升
- 全量 adaptive_graph_rerank vs vector-only Recall@10 相对提升：8.93%
- Comparison holdout 子集结论：未达到 20% 相对提升
- Comparison holdout adaptive_graph_rerank vs vector-only Recall@10 相对提升：12.66%

## 实验方法

本实验使用 MultiHop-RAG 官方数据集评估多跳检索。索引阶段只使用 corpus 正文与元数据；query 的 `evidence_list` 只用于计算指标，不参与向量索引或图关系构建。

### 数据集

- 数据来源：MultiHop-RAG `MultiHopRAG.json` 与 `corpus.json`
- Query 抽样：跳过 `null_query`，固定随机种子 `20260706` 抽取 500 条
- 金标：每条 query 的证据标题集合
- 问题类型分布：

```json
{
  "inference_query": 190,
  "comparison_query": 171,
  "temporal_query": 139
}
```

### 基线

- `vector_only`：Ollama `qwen3-embedding:4b` 生成 2560 维向量，Milvus 以 COSINE 检索文档。
- `bm25_only`：本地 BM25 关键词召回，作为传统稀疏检索基线。
- `graph_only`：BM25 种子召回 + Neo4j 文档实体/元数据关系扩展。
- `hybrid_rrf`：将 Milvus 向量排名和 Neo4j 图扩展排名用 RRF 融合。
- `metadata_graph_rerank`：在 Milvus top-50 与 BM25 top-50 候选上，用向量分、BM25 分、source、实体、标题/正文 token overlap 做无监督重排。
- `adaptive_graph_rerank`：对 comparison-like query 使用更重的 BM25/source 权重，其余 query 使用通用 metadata rerank 权重；query 类型由文本规则识别，不使用金标证据。

### 开发集/留出集设定

- `dev_first_200`：用于快速失败分析和权重选择。
- `holdout_after_200`：未参与权重选择，用于检验泛化。
- 报告同时给出全量、holdout 和官方 `question_type` 分类型指标，避免只看最有利切片。

### 指标

- `Recall@5/10`：top-k 中命中的证据标题数量 / 金标证据标题数量。
- `Hit@10`：top-10 中是否至少命中一个证据标题。
- `MRR@10`：第一个命中证据标题的倒数排名。
- `nDCG@10`：按证据标题命中计算的归一化折损累计增益。

## 结果

| 模式 | Recall@5 | Recall@10 | Hit@10 | MRR@10 | nDCG@10 | 平均耗时(s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| vector_only | 65.17% | 79.73% | 97.80% | 78.25% | 68.34% | 0.0045 |
| bm25_only | 63.47% | 77.05% | 96.00% | 75.12% | 65.97% | 0.0057 |
| graph_only | 48.35% | 71.33% | 95.40% | 56.87% | 52.51% | 0.0057 |
| hybrid_rrf | 65.17% | 79.10% | 98.40% | 78.31% | 68.08% | 0.0103 |
| metadata_graph_rerank | 73.82% | 86.62% | 99.40% | 85.27% | 76.68% | 0.0161 |
| adaptive_graph_rerank | 74.30% | 86.85% | 99.40% | 83.99% | 76.49% | 0.0161 |

## 提升率

```text
adaptive_graph_rerank_vs_vector_recall_at_10 = (adaptive_graph_rerank_recall_at_10 - vector_only_recall_at_10) / vector_only_recall_at_10
```

当前全量结果：8.93%

## 分类型结果

全量 question_type Recall@10：

```json
{
  "inference_query": {
    "vector_only": 0.7895,
    "metadata_graph_rerank": 0.8232,
    "adaptive_graph_rerank": 0.8224,
    "relative_lifts": {
      "bm25_only_vs_vector_recall_at_10": -0.0706,
      "graph_only_vs_vector_recall_at_10": -0.0812,
      "hybrid_rrf_vs_vector_recall_at_10": -0.0233,
      "metadata_graph_rerank_vs_vector_recall_at_10": 0.0427,
      "adaptive_graph_rerank_vs_vector_recall_at_10": 0.0417
    }
  },
  "comparison_query": {
    "vector_only": 0.7817,
    "metadata_graph_rerank": 0.9006,
    "adaptive_graph_rerank": 0.8996,
    "relative_lifts": {
      "bm25_only_vs_vector_recall_at_10": 0.01,
      "graph_only_vs_vector_recall_at_10": -0.1222,
      "hybrid_rrf_vs_vector_recall_at_10": 0.0349,
      "metadata_graph_rerank_vs_vector_recall_at_10": 0.1521,
      "adaptive_graph_rerank_vs_vector_recall_at_10": 0.1508
    }
  },
  "temporal_query": {
    "vector_only": 0.8273,
    "metadata_graph_rerank": 0.8825,
    "adaptive_graph_rerank": 0.8933,
    "relative_lifts": {
      "bm25_only_vs_vector_recall_at_10": -0.0361,
      "graph_only_vs_vector_recall_at_10": -0.1174,
      "hybrid_rrf_vs_vector_recall_at_10": -0.0376,
      "metadata_graph_rerank_vs_vector_recall_at_10": 0.0667,
      "adaptive_graph_rerank_vs_vector_recall_at_10": 0.0798
    }
  }
}
```

Holdout question_type Recall@10：

```json
{
  "inference_query": {
    "vector_only": 0.7873,
    "metadata_graph_rerank": 0.8268,
    "adaptive_graph_rerank": 0.8304,
    "relative_lifts": {
      "bm25_only_vs_vector_recall_at_10": -0.0669,
      "graph_only_vs_vector_recall_at_10": -0.078,
      "hybrid_rrf_vs_vector_recall_at_10": -0.0084,
      "metadata_graph_rerank_vs_vector_recall_at_10": 0.0502,
      "adaptive_graph_rerank_vs_vector_recall_at_10": 0.0547
    }
  },
  "comparison_query": {
    "vector_only": 0.8114,
    "metadata_graph_rerank": 0.936,
    "adaptive_graph_rerank": 0.9141,
    "relative_lifts": {
      "bm25_only_vs_vector_recall_at_10": 0.0124,
      "graph_only_vs_vector_recall_at_10": -0.1203,
      "hybrid_rrf_vs_vector_recall_at_10": 0.0249,
      "metadata_graph_rerank_vs_vector_recall_at_10": 0.1536,
      "adaptive_graph_rerank_vs_vector_recall_at_10": 0.1266
    }
  },
  "temporal_query": {
    "vector_only": 0.8027,
    "metadata_graph_rerank": 0.8487,
    "adaptive_graph_rerank": 0.8659,
    "relative_lifts": {
      "bm25_only_vs_vector_recall_at_10": -0.0287,
      "graph_only_vs_vector_recall_at_10": -0.1003,
      "hybrid_rrf_vs_vector_recall_at_10": -0.0453,
      "metadata_graph_rerank_vs_vector_recall_at_10": 0.0573,
      "adaptive_graph_rerank_vs_vector_recall_at_10": 0.0787
    }
  }
}
```

## 复现命令

```bash
conda run -n rag python evals/rag/run_multihop_retrieval_eval.py --query-limit 500 --top-k 50
```

## 输出文件

- 配置：`evals/results/rag/rag_multihop_adaptive_500_20260706/config.json`
- 原始检索结果：`evals/results/rag/rag_multihop_adaptive_500_20260706/raw_retrieval.jsonl`
- 指标：`evals/results/rag/rag_multihop_adaptive_500_20260706/metrics.json`
- 本报告：`evals/reports/multihop_rag_retrieval_evaluation.md`

## 注意事项

- 该实验为了避免答案泄漏，Neo4j 图只由 corpus 文本中的实体、source、category 构成，未使用 gold evidence 构边。
- 当前最有效的提升来自 metadata-aware rerank，而不是原始 RRF；这说明多跳任务的主要瓶颈是 top-50 候选排序和证据覆盖。
- 如果要把“多跳召回提升 20%”写进简历，必须以 holdout 或更大样本上的结果为准；本报告不会把 dev 局部结果包装成最终结论。
