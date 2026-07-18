# MultiHop-RAG LambdaMART 重排序实验

## 结论

- 运行编号：`rag_lambdamart_enriched_train1300_dev200_20260707`
- 数据集：MultiHop-RAG 官方数据，跳过 `null_query` 后共 `2255` 条可评估 query
- 训练集：`1300` 条
- Dev 集：`200` 条
- Holdout 集：`755` 条
- 主指标：`Recall@10`
- 结果：达到 20% 严格 holdout 提升
- Holdout 最佳相对提升：`22.34%`
- 结果目录：`D:\学习笔记\langchain\rag_upper\evals\results\rag\rag_lambdamart_enriched_train1300_dev200_20260707`

## 实验方法

本实验使用 LightGBM LambdaMART 学习排序模型，在文档级向量、BM25、chunk 级向量三路召回组成的候选集上进行重排序。MultiHop-RAG 的金标证据标题只用于训练集内的排序标签，以及 holdout 上的最终评分；holdout 不参与模型拟合。

## 特征

特征列表：

```json
[
  "vector_present",
  "vector_score",
  "vector_rr",
  "bm25_present",
  "bm25_score",
  "bm25_rr",
  "chunk_present",
  "chunk_score",
  "chunk_rr",
  "chunk_hit_count",
  "chunk_score_sum",
  "chunk_top3_mean",
  "rrf_score",
  "source_match",
  "source_token_overlap",
  "category_overlap",
  "title_overlap",
  "body_overlap_1400",
  "body_overlap_4000",
  "entity_title_match",
  "entity_body_match",
  "entity_source_match",
  "date_match",
  "published_year_match",
  "query_token_count",
  "query_entity_count",
  "query_number_count",
  "query_has_source_mention",
  "query_is_comparison_like",
  "query_is_temporal_like",
  "doc_title_token_count",
  "doc_body_token_count",
  "doc_body_char_count"
]
```

## Holdout 结果

| 模式 | Recall@5 | Recall@10 | Hit@10 | MRR@10 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| vector_only | 62.95% | 78.97% | 96.69% | 74.23% | 66.67% |
| bm25_only | 66.05% | 78.42% | 97.62% | 76.54% | 67.80% |
| chunk_vector | 65.99% | 81.89% | 98.68% | 77.82% | 69.96% |
| lambdamart | 90.02% | 96.56% | 99.87% | 96.97% | 92.29% |
| lambdamart_source_coverage | 90.02% | 96.61% | 99.87% | 96.97% | 92.31% |

相对 `vector_only` 的提升：

```json
{
  "bm25_only_vs_vector_recall_at_10": -0.007,
  "chunk_vector_vs_vector_recall_at_10": 0.037,
  "lambdamart_vs_vector_recall_at_10": 0.2227,
  "lambdamart_source_coverage_vs_vector_recall_at_10": 0.2234
}
```

## 复现命令

```bash
conda run -n rag python evals/rag/run_multihop_lambdamart_eval.py --query-limit 2556 --train-size 1300 --dev-size 200 --candidate-top-k 100 --chunk-top-k 400 --num-leaves 63 --n-estimators 650
```
