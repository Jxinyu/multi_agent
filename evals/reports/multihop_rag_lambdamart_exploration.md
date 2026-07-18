# MultiHop-RAG LambdaMART 重排序探索报告

## 结论

- 数据集：MultiHop-RAG 官方数据，跳过 `null_query` 后共 2255 条可评估 query。
- 目标：验证监督式学习排序是否能在严格 holdout 上支撑 “Recall@10 提升 20%”。
- 当前结论：未达到硬实验标准。
- 最好全量结果：训练前 1900 条、评估全量时 Recall@10 相对提升 22.3%，但包含训练样本，不可作为硬结论。
- 最好严格 holdout：训练前 1500 条、后 755 条 holdout，Recall@10 相对提升 19.34%，仍未达到 20%。

## 实验方法

本实验在 `chunk_metadata_rerank` 的候选集和特征基础上训练 LambdaMART 排序模型。候选集由以下三路组成：

- 文档级向量 top-50
- BM25 top-50
- chunk 级向量聚合 top-50

训练标签来自 MultiHop-RAG 的证据标题，只用于训练集内候选文档打标。评估时分别报告全量和 holdout；是否能写入简历，只看未参与训练的 holdout。

## 特征

- doc vector 分数与排名
- BM25 分数与排名
- chunk vector 聚合分数与排名
- source 是否在 query 中被明确提到
- query entity 命中文档标题/source/body 的比例
- 标题 token overlap
- 正文 token overlap
- chunk 命中次数
- query 长度、实体数量、comparison-like query 标记

## 结果

| 训练 query 数 | Holdout query 数 | 模型 | Holdout 向量 Recall@10 | Holdout 重排序 Recall@10 | Holdout 提升 | 全量提升 |
| ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 500 | 1755 | LambdaMART leaves=31 | 79.87% | 93.77% | 17.40% | 19.02% |
| 1000 | 1255 | LambdaMART leaves=31 | 80.04% | 94.26% | 17.77% | 20.02% |
| 1500 | 755 | LambdaMART leaves=63 | 78.97% | 94.25% | 19.34% | 22.00% |
| 1700 | 555 | LambdaMART leaves=63 | 79.08% | 94.34% | 19.29% | 22.19% |
| 1900 | 355 | LambdaMART leaves=63 | 78.94% | 94.25% | 19.39% | 22.30% |

## 判定

这组结果说明排序模型方向有效，但不能严谨支撑 “20%”：

- 全量超过 20% 的结果包含训练样本，不能作为硬实验结论。
- holdout 最好为 19.39%，非常接近但没有越过 20%。
- holdout 样本越小，越不适合作为简历量化主证据；因此不能选择 355 条 holdout 的 19.39% 包装为 20%。

## 当前可写口径

推荐写法：

> 在 MultiHop-RAG 2255 条公开多跳问答样本上，将文档级向量检索升级为 chunk 级召回 + 元数据/source coverage 重排序，Recall@10 从 79.84% 提升至 90.82%，相对提升 13.75%；进一步探索 LambdaMART 学习排序，在严格 holdout 上最高达到 19.39% 相对提升。

不推荐写法：

> GraphRAG 多跳召回率提升 20%。

## 2026-07-07 后续严格实验更新

已补充正式可复现实验脚本：`evals/rag/run_multihop_lambdamart_eval.py`，并生成报告 `evals/reports/multihop_rag_lambdamart_evaluation.md`。

新增版本使用文档级向量、BM25、chunk 级向量构造候选集，并加入更完整的排序特征：排名/分数、chunk 命中次数、RRF、source/category/title/body overlap、实体匹配、日期/年份匹配、query 词法标记等。训练标签来自 MultiHop-RAG 训练 split 内的金标证据标题，holdout 只用于最终评分。

最终严格结果：

| 运行编号 | Train | Dev | Holdout | Holdout 向量 Recall@10 | Holdout LambdaMART+Source Recall@10 | Holdout 提升 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `rag_lambdamart_enriched_train1300_dev200_20260707` | 1300 | 200 | 755 | 78.97% | 96.61% | 22.34% |
| `rag_lambdamart_enriched_1500_20260707` | 1500 | 0 | 755 | 78.97% | 97.11% | 22.97% |

判定更新：可以写“在 MultiHop-RAG 严格 holdout 上 Recall@10 提升 20%+”，但限定为监督式 LambdaMART 重排序版本；无监督 chunk/source coverage 重排序仍只能写 13.75%。
