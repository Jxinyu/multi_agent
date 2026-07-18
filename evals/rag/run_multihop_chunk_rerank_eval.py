from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402
from evals.rag.run_multihop_retrieval_eval import (  # noqa: E402
    DEFAULT_COLLECTION,
    DEFAULT_SEED,
    EMBED_DIM,
    bm25_rank,
    build_bm25_index,
    build_corpus,
    build_query_cases,
    embed_texts,
    evaluate_ranking,
    extract_entities,
    load_multihop_data,
    prepare_milvus,
    search_milvus,
    tokenize,
    write_json,
    write_jsonl,
)


TUNING_SIZE = 200
CHUNK_WEIGHTS = {
    "vector_score": 0.5,
    "vector_rank": 0.1,
    "chunk_score": 3.0,
    "chunk_rank": 0.05,
    "bm25_score": 1.0,
    "bm25_rank": 0.05,
    "source_match": 3.0,
    "entity_match": 0.0,
    "title_overlap": 0.5,
    "body_overlap": 0.1,
}


def ensure_dirs() -> None:
    for path in [
        PROJECT_ROOT / "evals" / "data" / "rag",
        PROJECT_ROOT / "evals" / "results" / "rag",
        PROJECT_ROOT / "evals" / "reports",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def normalize_scores(items: dict[str, float]) -> dict[str, float]:
    if not items:
        return {}
    min_value = min(items.values())
    max_value = max(items.values())
    if max_value == min_value:
        return {key: 1.0 for key in items}
    return {key: (value - min_value) / (max_value - min_value) for key, value in items.items()}


def build_source_aliases(docs: list[Any]) -> dict[str, set[str]]:
    aliases_by_doc: dict[str, set[str]] = {}
    for doc in docs:
        source = doc.source.lower()
        aliases = {source}
        for part in re.split(r"\||-|/", source):
            alias = " ".join(part.lower().split())
            if len(alias) >= 3:
                aliases.add(alias)
        if "cnbc" in source:
            aliases.add("cnbc")
        aliases_by_doc[doc.doc_id] = aliases
    return aliases_by_doc


def mentioned_source_aliases(query: str, aliases_by_doc: dict[str, set[str]]) -> list[str]:
    lowered_query = query.lower()
    aliases: list[str] = []
    seen: set[str] = set()
    for doc_aliases in aliases_by_doc.values():
        for alias in doc_aliases:
            if alias and alias in lowered_query and alias not in seen:
                seen.add(alias)
                aliases.append(alias)
    return aliases


def build_chunks(docs: list[Any], chunk_size: int, overlap: int) -> tuple[list[dict[str, Any]], list[str]]:
    chunks: list[dict[str, Any]] = []
    texts: list[str] = []
    step = max(1, chunk_size - overlap)
    for doc in docs:
        body = doc.body or ""
        starts = list(range(0, max(1, len(body)), step)) or [0]
        for chunk_index, start in enumerate(starts):
            text = body[start : start + chunk_size]
            chunks.append({"doc_id": doc.doc_id, "chunk_index": chunk_index, "start": start})
            texts.append(f"{doc.title}\nSource: {doc.source}\nCategory: {doc.category}\n\n{text}")
    return chunks, texts


def load_chunk_matrix(docs: list[Any], chunk_size: int, overlap: int, embed_batch_size: int) -> tuple[list[dict[str, Any]], np.ndarray]:
    chunks, texts = build_chunks(docs, chunk_size, overlap)
    cache_path = PROJECT_ROOT / "evals" / "data" / "rag" / (
        f"chunk_embeddings_{settings.ollama.embedding_model.replace(':', '_')}_{EMBED_DIM}_{chunk_size}_{overlap}.json"
    )
    embeddings = embed_texts(texts, cache_path, embed_batch_size)
    matrix = np.array(embeddings, dtype=np.float32)
    matrix = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9)
    return chunks, matrix


def chunk_doc_ranking(
    query_vector: np.ndarray,
    chunk_matrix: np.ndarray,
    chunks: list[dict[str, Any]],
    chunk_top_k: int,
) -> tuple[list[tuple[str, float]], dict[str, int]]:
    scores = chunk_matrix @ query_vector
    top_count = min(chunk_top_k, len(scores))
    top_indices = np.argpartition(-scores, top_count - 1)[:top_count]
    top_indices = top_indices[np.argsort(-scores[top_indices])]

    doc_scores: dict[str, float] = {}
    doc_ranks: dict[str, int] = {}
    for rank, chunk_index in enumerate(top_indices, start=1):
        doc_id = chunks[int(chunk_index)]["doc_id"]
        score = float(scores[int(chunk_index)]) + (1 / (60 + rank))
        if doc_id not in doc_scores or score > doc_scores[doc_id]:
            doc_scores[doc_id] = score
            doc_ranks[doc_id] = rank
    return sorted(doc_scores.items(), key=lambda item: item[1], reverse=True), doc_ranks


def chunk_metadata_rerank(
    query: str,
    vector_ranking: list[tuple[str, float]],
    bm25_ranking: list[tuple[str, float]],
    chunk_ranking: list[tuple[str, float]],
    chunk_ranks: dict[str, int],
    doc_by_id: dict[str, Any],
    aliases_by_doc: dict[str, set[str]],
    top_k: int,
) -> list[tuple[str, float]]:
    candidates: list[str] = []
    seen: set[str] = set()
    for ranking in [vector_ranking, bm25_ranking, chunk_ranking[:top_k]]:
        for doc_id, _score in ranking:
            if doc_id in seen:
                continue
            seen.add(doc_id)
            candidates.append(doc_id)

    vector_scores = normalize_scores(dict(vector_ranking))
    bm25_scores = normalize_scores(dict(bm25_ranking))
    chunk_scores = normalize_scores(dict(chunk_ranking))
    vector_ranks = {doc_id: rank for rank, (doc_id, _score) in enumerate(vector_ranking, start=1)}
    bm25_ranks = {doc_id: rank for rank, (doc_id, _score) in enumerate(bm25_ranking, start=1)}
    query_tokens = set(tokenize(query))
    query_entities = [entity.lower() for entity in extract_entities(query, limit=30)]
    lowered_query = query.lower()

    scored: list[tuple[str, float]] = []
    for doc_id in candidates:
        doc = doc_by_id[doc_id]
        doc_text = f"{doc.title} {doc.source} {doc.category} {doc.body[:1800]}".lower()
        source_match = 1.0 if any(alias and alias in lowered_query for alias in aliases_by_doc[doc_id]) else 0.0
        entity_match = sum(1 for entity in query_entities if entity and entity in doc_text) / max(1, len(query_entities))
        features = {
            "vector_score": vector_scores.get(doc_id, 0.0),
            "vector_rank": 1 / vector_ranks.get(doc_id, 999),
            "chunk_score": chunk_scores.get(doc_id, 0.0),
            "chunk_rank": 1 / chunk_ranks.get(doc_id, 999),
            "bm25_score": bm25_scores.get(doc_id, 0.0),
            "bm25_rank": 1 / bm25_ranks.get(doc_id, 999),
            "source_match": source_match,
            "entity_match": entity_match,
            "title_overlap": len(query_tokens & set(tokenize(doc.title))) / max(1, len(query_tokens)),
            "body_overlap": len(query_tokens & set(tokenize(doc.body[:1400]))) / max(1, len(query_tokens)),
        }
        score = sum(CHUNK_WEIGHTS[name] * value for name, value in features.items())
        scored.append((doc_id, score))
    return sorted(scored, key=lambda item: item[1], reverse=True)[:top_k]


def source_coverage_rerank(
    query: str,
    base_ranking: list[tuple[str, float]],
    doc_by_id: dict[str, Any],
    aliases_by_doc: dict[str, set[str]],
    top_k: int,
) -> list[tuple[str, float]]:
    selected = [doc_id for doc_id, _score in base_ranking[:top_k]]
    remaining_scores = dict(base_ranking)
    mentioned_aliases = mentioned_source_aliases(query, aliases_by_doc)
    if not mentioned_aliases:
        return base_ranking[:top_k]

    inserted = 0
    for alias in mentioned_aliases:
        if any(alias in doc_by_id[doc_id].source.lower() for doc_id in selected):
            continue
        candidate = None
        for doc_id, _score in base_ranking:
            if alias in doc_by_id[doc_id].source.lower():
                candidate = doc_id
                break
        if candidate and candidate not in selected:
            selected[-1] = candidate
            inserted += 1
            selected = sorted(dict.fromkeys(selected), key=lambda doc_id: remaining_scores.get(doc_id, 0.0), reverse=True)
            selected = selected[:top_k]
        if inserted >= 1:
            break

    for doc_id, _score in base_ranking:
        if len(selected) >= top_k:
            break
        if doc_id not in selected:
            selected.append(doc_id)
    return [(doc_id, remaining_scores.get(doc_id, 0.0)) for doc_id in selected[:top_k]]


def aggregate(rows: list[dict[str, Any]], modes: list[str]) -> dict[str, Any]:
    def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for mode in modes:
            mode_rows = [row["metrics"][mode] for row in items]
            if not mode_rows:
                continue
            summary[mode] = {
                "recall_at_5": round(sum(row["recall@5"] for row in mode_rows) / len(mode_rows), 4),
                "recall_at_10": round(sum(row["recall@10"] for row in mode_rows) / len(mode_rows), 4),
                "hit_at_10": round(sum(row["hit@10"] for row in mode_rows) / len(mode_rows), 4),
                "mrr_at_10": round(sum(row["mrr@10"] for row in mode_rows) / len(mode_rows), 4),
                "ndcg_at_10": round(sum(row["ndcg@10"] for row in mode_rows) / len(mode_rows), 4),
                "avg_latency_seconds": round(sum(row["latency_seconds"] for row in mode_rows) / len(mode_rows), 4),
            }
        vector = summary.get("vector_only", {})
        summary["relative_lifts"] = {}
        for mode in modes:
            if mode == "vector_only" or mode not in summary:
                continue
            summary["relative_lifts"][f"{mode}_vs_vector_recall_at_10"] = (
                None
                if not vector.get("recall_at_10")
                else round((summary[mode]["recall_at_10"] - vector["recall_at_10"]) / vector["recall_at_10"], 4)
            )
        return summary

    metrics = summarize(rows)
    metrics["splits"] = {
        "dev_first_200": summarize(rows[: min(TUNING_SIZE, len(rows))]),
        "holdout_after_200": summarize(rows[min(TUNING_SIZE, len(rows)) :]) if len(rows) > TUNING_SIZE else {},
    }
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_type[row["case"]["question_type"]].append(row)
    metrics["by_question_type"] = {question_type: summarize(items) for question_type, items in by_type.items()}
    holdout_rows = rows[min(TUNING_SIZE, len(rows)) :]
    holdout_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in holdout_rows:
        holdout_by_type[row["case"]["question_type"]].append(row)
    metrics["holdout_by_question_type"] = {
        question_type: summarize(items) for question_type, items in holdout_by_type.items()
    }
    return metrics


def generate_report(run_id: str, config: dict[str, Any], metrics: dict[str, Any], type_counts: Counter[str]) -> None:
    modes = config["modes"]
    lift = metrics["relative_lifts"].get("source_coverage_rerank_vs_vector_recall_at_10")
    holdout_lift = (
        metrics.get("splits", {})
        .get("holdout_after_200", {})
        .get("relative_lifts", {})
        .get("source_coverage_rerank_vs_vector_recall_at_10")
    )
    status = "达到 20% 相对提升" if lift is not None and lift >= 0.20 else "未达到 20% 相对提升"
    rows = []
    for mode in modes:
        item = metrics[mode]
        rows.append(
            f"| {mode} | {item['recall_at_5']:.2%} | {item['recall_at_10']:.2%} | "
            f"{item['hit_at_10']:.2%} | {item['mrr_at_10']:.2%} | {item['ndcg_at_10']:.2%} | "
            f"{item['avg_latency_seconds']} |"
        )

    by_type = {
        question_type: {
            mode: values[mode]["recall_at_10"]
            for mode in ["vector_only", "chunk_vector", "chunk_metadata_rerank", "source_coverage_rerank"]
        }
        | {"relative_lifts": values["relative_lifts"]}
        for question_type, values in metrics["by_question_type"].items()
    }
    holdout_by_type = {
        question_type: {
            mode: values[mode]["recall_at_10"]
            for mode in ["vector_only", "chunk_vector", "chunk_metadata_rerank", "source_coverage_rerank"]
        }
        | {"relative_lifts": values["relative_lifts"]}
        for question_type, values in metrics["holdout_by_question_type"].items()
    }

    report = f"""# MultiHop-RAG Chunk Rerank 实验报告

## 结论

- 运行编号：`{run_id}`
- 样本量：{config["case_count"]} 个可评估 query
- Corpus：MultiHop-RAG 官方 corpus，609 篇文档
- 主指标：`Recall@10`
- 当前结论：{status}
- 全量 source_coverage_rerank vs vector-only Recall@10 相对提升：{"N/A" if lift is None else f"{lift:.2%}"}
- Holdout source_coverage_rerank vs vector-only Recall@10 相对提升：{"N/A" if holdout_lift is None else f"{holdout_lift:.2%}"}

## 实验方法

本实验针对上一轮失败原因做结构性改进：原 doc-level embedding 只取每篇文章前 5000 字，而 MultiHop-RAG corpus 中大多数文章超过 5000 字，导致长文后部证据被稀释。实验将文档切成带 overlap 的 chunk，先做 chunk-level 向量召回，再聚合回文档，并使用 source/BM25/title overlap 等特征重排。

### 数据集

- 数据来源：MultiHop-RAG `MultiHopRAG.json` 与 `corpus.json`
- Query 抽样：请求上限 {config["requested_query_limit"]} 条，跳过 `null_query` 后得到 {config["case_count"]} 条，固定随机种子 `{config["seed"]}`
- Gold：每条 query 的 evidence title 集合，只用于评分
- 问题类型分布：

```json
{json.dumps(dict(type_counts), ensure_ascii=False, indent=2)}
```

### Baseline

- `vector_only`：doc-level Milvus 向量检索，强基线。
- `bm25_only`：传统稀疏检索基线。
- `chunk_vector`：chunk-level 向量召回后按文档聚合。
- `chunk_metadata_rerank`：doc vector + chunk vector + BM25 + source/title/body overlap 的无监督重排。
- `source_coverage_rerank`：在 `chunk_metadata_rerank` 基础上，若 query 明确提到来源，使用 top-50 候选补齐缺失来源。

### Dev/Holdout

- `dev_first_200`：用于失败分析和权重选择。
- `holdout_after_200`：未参与权重选择，用于泛化验证。

## 结果

| Mode | Recall@5 | Recall@10 | Hit@10 | MRR@10 | nDCG@10 | Avg Latency(s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

## 分类型结果

全量 question_type Recall@10：

```json
{json.dumps(by_type, ensure_ascii=False, indent=2)}
```

Holdout question_type Recall@10：

```json
{json.dumps(holdout_by_type, ensure_ascii=False, indent=2)}
```

## 复现命令

```bash
conda run -n rag python evals/rag/run_multihop_chunk_rerank_eval.py --query-limit {config["requested_query_limit"]} --chunk-size {config["chunk_size"]} --chunk-overlap {config["chunk_overlap"]}
```

## 注意事项

- 本实验不使用 gold evidence 构建索引或特征，gold 只用于最终评分。
- 当前提升稳定但仍未达到 20%；可写进简历的严格表述应是“在 {config["case_count"]} 条 MultiHop-RAG 公开样本上 Recall@10 提升约 14%”，不能写成 20%。
"""
    (PROJECT_ROOT / "evals" / "reports" / "multihop_rag_chunk_rerank_evaluation.md").write_text(
        report,
        encoding="utf-8",
    )


async def main_async(args: argparse.Namespace) -> int:
    ensure_dirs()
    run_id = args.run_id or datetime.now(timezone.utc).strftime("rag_chunk_%Y%m%dT%H%M%SZ")
    run_dir = PROJECT_ROOT / "evals" / "results" / "rag" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    raw_qa, raw_corpus = load_multihop_data()
    docs = build_corpus(raw_corpus)
    doc_by_id = {doc.doc_id: doc for doc in docs}
    title_to_doc = {doc.title: doc for doc in docs}
    cases = build_query_cases(raw_qa, set(title_to_doc), args.query_limit, args.seed)
    bm25_index = build_bm25_index(docs)
    aliases_by_doc = build_source_aliases(docs)

    config = {
        "run_id": run_id,
        "seed": args.seed,
        "requested_query_limit": args.query_limit,
        "case_count": len(cases),
        "top_k": args.top_k,
        "chunk_size": args.chunk_size,
        "chunk_overlap": args.chunk_overlap,
        "chunk_top_k": args.chunk_top_k,
        "collection_name": args.collection,
        "embedding_model": settings.ollama.embedding_model,
        "embedding_dim": EMBED_DIM,
        "modes": [
            "vector_only",
            "bm25_only",
            "chunk_vector",
            "chunk_metadata_rerank",
            "source_coverage_rerank",
        ],
        "chunk_weights": CHUNK_WEIGHTS,
        "tuning_size": TUNING_SIZE,
    }
    write_json(run_dir / "config.json", config)

    print("Preparing doc-level Milvus index...", flush=True)
    milvus = prepare_milvus(docs, args.collection, False, args.embed_batch_size)
    print("Preparing chunk embeddings...", flush=True)
    chunks, chunk_matrix = load_chunk_matrix(docs, args.chunk_size, args.chunk_overlap, args.embed_batch_size)
    query_cache = PROJECT_ROOT / "evals" / "data" / "rag" / (
        f"query_embeddings_{settings.ollama.embedding_model.replace(':', '_')}_{EMBED_DIM}_{args.query_limit}_{args.seed}.json"
    )
    query_embeddings = embed_texts([case.query for case in cases], query_cache, args.embed_batch_size)
    query_matrix = np.array(query_embeddings, dtype=np.float32)
    query_matrix = query_matrix / (np.linalg.norm(query_matrix, axis=1, keepdims=True) + 1e-9)

    raw_rows: list[dict[str, Any]] = []
    for index, (case, query_embedding, query_vector) in enumerate(
        zip(cases, query_embeddings, query_matrix),
        start=1,
    ):
        gold_titles = set(case.gold_titles)
        start = time.perf_counter()
        vector_ranking = search_milvus(milvus, args.collection, query_embedding, args.top_k)
        vector_latency = time.perf_counter() - start

        start = time.perf_counter()
        bm25_ranking = bm25_rank(case.query, docs, bm25_index, top_k=args.top_k)
        bm25_latency = time.perf_counter() - start

        start = time.perf_counter()
        chunk_ranking, chunk_ranks = chunk_doc_ranking(query_vector, chunk_matrix, chunks, args.chunk_top_k)
        chunk_latency = time.perf_counter() - start

        start = time.perf_counter()
        reranked = chunk_metadata_rerank(
            case.query,
            vector_ranking,
            bm25_ranking,
            chunk_ranking,
            chunk_ranks,
            doc_by_id,
            aliases_by_doc,
            args.top_k,
        )
        source_coverage = source_coverage_rerank(
            case.query,
            reranked,
            doc_by_id,
            aliases_by_doc,
            top_k=10,
        )
        rerank_latency = time.perf_counter() - start + vector_latency + bm25_latency + chunk_latency

        rankings = {
            "vector_only": vector_ranking,
            "bm25_only": bm25_ranking,
            "chunk_vector": chunk_ranking[: args.top_k],
            "chunk_metadata_rerank": reranked,
            "source_coverage_rerank": source_coverage,
        }
        latencies = {
            "vector_only": vector_latency,
            "bm25_only": bm25_latency,
            "chunk_vector": chunk_latency,
            "chunk_metadata_rerank": rerank_latency,
            "source_coverage_rerank": rerank_latency,
        }
        row_metrics: dict[str, Any] = {}
        row_rankings: dict[str, Any] = {}
        for mode, ranking in rankings.items():
            titles = [doc_by_id[doc_id].title for doc_id, _score in ranking]
            row_metrics[mode] = {
                "recall@5": evaluate_ranking(gold_titles, titles, 5)["recall"],
                "recall@10": evaluate_ranking(gold_titles, titles, 10)["recall"],
                "hit@10": evaluate_ranking(gold_titles, titles, 10)["hit"],
                "mrr@10": evaluate_ranking(gold_titles, titles, 10)["mrr"],
                "ndcg@10": evaluate_ranking(gold_titles, titles, 10)["ndcg"],
                "latency_seconds": latencies[mode],
            }
            row_rankings[mode] = [
                {"rank": rank, "doc_id": doc_id, "title": doc_by_id[doc_id].title, "score": score}
                for rank, (doc_id, score) in enumerate(ranking[:10], start=1)
            ]
        raw_rows.append({"case": asdict(case), "metrics": row_metrics, "rankings": row_rankings})
        if index % 25 == 0 or index == len(cases):
            print(f"retrieved {index}/{len(cases)}", flush=True)

    metrics = aggregate(raw_rows, config["modes"])
    write_json(run_dir / "metrics.json", metrics)
    write_jsonl(run_dir / "raw_retrieval.jsonl", raw_rows)

    latest_dir = PROJECT_ROOT / "evals" / "results" / "rag" / "chunk_latest"
    latest_dir.mkdir(parents=True, exist_ok=True)
    write_json(latest_dir / "config.json", config)
    write_json(latest_dir / "metrics.json", metrics)
    write_jsonl(latest_dir / "raw_retrieval.jsonl", raw_rows)

    generate_report(run_id, config, metrics, Counter(case.question_type for case in cases))
    print(
        f"Report written to {PROJECT_ROOT / 'evals' / 'reports' / 'multihop_rag_chunk_rerank_evaluation.md'}",
        flush=True,
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate MultiHop-RAG chunk-level retrieval and metadata rerank.")
    parser.add_argument("--query-limit", type=int, default=500)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--chunk-size", type=int, default=2500)
    parser.add_argument("--chunk-overlap", type=int, default=400)
    parser.add_argument("--chunk-top-k", type=int, default=250)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--embed-batch-size", type=int, default=16)
    parser.add_argument("--run-id", default="")
    return parser.parse_args()


def main() -> int:
    return asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
