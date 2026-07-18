# MultiHop-RAG Chunk 重排序实验报告

## 结论

- 运行编号：`rag_chunk_source_coverage_full_20260707`
- 样本量：2255 个可评估 query
- Corpus：MultiHop-RAG 官方 corpus，609 篇文档
- 主指标：`Recall@10`
- 当前结论：未达到 20% 相对提升
- 全量 source_coverage_rerank vs vector-only Recall@10 相对提升：13.75%
- Holdout source_coverage_rerank vs vector-only Recall@10 相对提升：13.71%

## 实验方法

本实验针对上一轮失败原因做结构性改进：原 doc-level embedding 只取每篇文章前 5000 字，而 MultiHop-RAG corpus 中大多数文章超过 5000 字，导致长文后部证据被稀释。实验将文档切成带 overlap 的 chunk，先做 chunk-level 向量召回，再聚合回文档，并使用 source/BM25/title overlap 等特征重排。

### 数据集

- 数据来源：MultiHop-RAG `MultiHopRAG.json` 与 `corpus.json`
- Query 抽样：请求上限 2556 条，跳过 `null_query` 后得到 2255 条，固定随机种子 `20260706`
- 金标：每条 query 的证据标题集合，只用于评分
- 问题类型分布：

```json
{
  "inference_query": 816,
  "comparison_query": 856,
  "temporal_query": 583
}
```

### 基线

- `vector_only`：doc-level Milvus 向量检索，强基线。
- `bm25_only`：传统稀疏检索基线。
- `chunk_vector`：chunk-level 向量召回后按文档聚合。
- `chunk_metadata_rerank`：doc vector + chunk vector + BM25 + source/title/body overlap 的无监督重排。
- `source_coverage_rerank`：在 `chunk_metadata_rerank` 基础上，若 query 明确提到来源，使用 top-50 候选补齐缺失来源。

### 开发集/留出集

- `dev_first_200`：用于失败分析和权重选择。
- `holdout_after_200`：未参与权重选择，用于泛化验证。

## 结果

| Mode | Recall@5 | Recall@10 | Hit@10 | MRR@10 | nDCG@10 | Avg Latency(s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| vector_only | 64.73% | 79.84% | 97.07% | 76.24% | 67.93% | 0.0044 |
| bm25_only | 65.50% | 78.37% | 97.61% | 76.73% | 67.66% | 0.0055 |
| chunk_vector | 67.45% | 82.89% | 98.63% | 77.23% | 70.26% | 0.0012 |
| chunk_metadata_rerank | 78.49% | 90.44% | 99.65% | 86.37% | 80.32% | 0.0193 |
| source_coverage_rerank | 78.49% | 90.82% | 99.65% | 86.37% | 80.47% | 0.0193 |

## 分类型结果

全量 question_type Recall@10：

```json
{
  "inference_query": {
    "vector_only": 0.7814,
    "chunk_vector": 0.7981,
    "chunk_metadata_rerank": 0.8688,
    "source_coverage_rerank": 0.8751,
    "relative_lifts": {
      "bm25_only_vs_vector_recall_at_10": -0.0673,
      "chunk_vector_vs_vector_recall_at_10": 0.0214,
      "chunk_metadata_rerank_vs_vector_recall_at_10": 0.1119,
      "source_coverage_rerank_vs_vector_recall_at_10": 0.1199
    }
  },
  "comparison_query": {
    "vector_only": 0.7901,
    "chunk_vector": 0.8355,
    "chunk_metadata_rerank": 0.928,
    "source_coverage_rerank": 0.9303,
    "relative_lifts": {
      "bm25_only_vs_vector_recall_at_10": 0.0104,
      "chunk_vector_vs_vector_recall_at_10": 0.0575,
      "chunk_metadata_rerank_vs_vector_recall_at_10": 0.1745,
      "source_coverage_rerank_vs_vector_recall_at_10": 0.1774
    }
  },
  "temporal_query": {
    "vector_only": 0.8345,
    "chunk_vector": 0.8625,
    "chunk_metadata_rerank": 0.9197,
    "source_coverage_rerank": 0.9222,
    "relative_lifts": {
      "bm25_only_vs_vector_recall_at_10": 0.0058,
      "chunk_vector_vs_vector_recall_at_10": 0.0336,
      "chunk_metadata_rerank_vs_vector_recall_at_10": 0.1021,
      "source_coverage_rerank_vs_vector_recall_at_10": 0.1051
    }
  }
}
```

Holdout question_type Recall@10：

```json
{
  "inference_query": {
    "vector_only": 0.7802,
    "chunk_vector": 0.7974,
    "chunk_metadata_rerank": 0.8679,
    "source_coverage_rerank": 0.8742,
    "relative_lifts": {
      "bm25_only_vs_vector_recall_at_10": -0.0664,
      "chunk_vector_vs_vector_recall_at_10": 0.022,
      "chunk_metadata_rerank_vs_vector_recall_at_10": 0.1124,
      "source_coverage_rerank_vs_vector_recall_at_10": 0.1205
    }
  },
  "comparison_query": {
    "vector_only": 0.7946,
    "chunk_vector": 0.8384,
    "chunk_metadata_rerank": 0.9313,
    "source_coverage_rerank": 0.9324,
    "relative_lifts": {
      "bm25_only_vs_vector_recall_at_10": 0.0107,
      "chunk_vector_vs_vector_recall_at_10": 0.0551,
      "chunk_metadata_rerank_vs_vector_recall_at_10": 0.172,
      "source_coverage_rerank_vs_vector_recall_at_10": 0.1734
    }
  },
  "temporal_query": {
    "vector_only": 0.8311,
    "chunk_vector": 0.861,
    "chunk_metadata_rerank": 0.9178,
    "source_coverage_rerank": 0.9206,
    "relative_lifts": {
      "bm25_only_vs_vector_recall_at_10": 0.0114,
      "chunk_vector_vs_vector_recall_at_10": 0.036,
      "chunk_metadata_rerank_vs_vector_recall_at_10": 0.1043,
      "source_coverage_rerank_vs_vector_recall_at_10": 0.1077
    }
  }
}
```

## 复现命令

```bash
conda run -n rag python evals/rag/run_multihop_chunk_rerank_eval.py --query-limit 2556 --chunk-size 2500 --chunk-overlap 400
```

## 注意事项

- 本实验不使用金标证据构建索引或特征，金标只用于最终评分。
- 当前提升稳定但仍未达到 20%；可写进简历的严格表述应是“在 2255 条 MultiHop-RAG 公开样本上 Recall@10 提升约 14%”，不能写成 20%。

## 后续监督排序结果

本无监督报告本身仍然只支持 13.75% 的提升。后续新增 `evals/rag/run_multihop_lambdamart_eval.py`，在同一 MultiHop-RAG 数据上训练 supervised LambdaMART reranker，并使用未参与训练的 755 条 holdout 验证：

- train 1300 / dev 200 / holdout 755：Recall@10 从 78.97% 提升到 96.61%，相对提升 22.34%。
- train 1500 / holdout 755：Recall@10 从 78.97% 提升到 97.11%，相对提升 22.97%。

因此“20%+”只能归因于 `chunk-level candidate generation + LambdaMART rerank` 的监督排序版本，不能归因于本报告中的无监督 source coverage rerank。
