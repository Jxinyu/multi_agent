from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import sys
import time
import warnings
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np

warnings.filterwarnings("ignore", message="X does not have valid feature names.*")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402
from evals.rag.run_multihop_chunk_rerank_eval import (  # noqa: E402
    build_source_aliases,
    load_chunk_matrix,
    mentioned_source_aliases,
)
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


FEATURE_NAMES = [
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
    "doc_body_char_count",
]


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


def is_comparison_like(query: str) -> bool:
    return bool(
        re.search(
            r"\b(compare|compared|comparison|whereas|while|both|same|different|difference|between|versus|vs)\b",
            query,
            flags=re.IGNORECASE,
        )
    )


def is_temporal_like(query: str) -> bool:
    return bool(
        re.search(
            r"\b(before|after|during|when|date|year|month|timeline|recent|latest|earlier|later|20\d{2})\b",
            query,
            flags=re.IGNORECASE,
        )
    )


def query_years(query: str) -> set[str]:
    return set(re.findall(r"\b(20\d{2})\b", query))


def ranking_maps(ranking: list[tuple[str, float]]) -> tuple[dict[str, float], dict[str, int]]:
    return dict(ranking), {doc_id: rank for rank, (doc_id, _score) in enumerate(ranking, start=1)}


def enriched_chunk_doc_features(
    query_vector: np.ndarray,
    chunk_matrix: np.ndarray,
    chunks: list[dict[str, Any]],
    chunk_top_k: int,
) -> tuple[list[tuple[str, float]], dict[str, dict[str, float]]]:
    scores = chunk_matrix @ query_vector
    top_count = min(chunk_top_k, len(scores))
    top_indices = np.argpartition(-scores, top_count - 1)[:top_count]
    top_indices = top_indices[np.argsort(-scores[top_indices])]

    per_doc_scores: dict[str, list[float]] = defaultdict(list)
    best_rank: dict[str, int] = {}
    for rank, chunk_index in enumerate(top_indices, start=1):
        doc_id = chunks[int(chunk_index)]["doc_id"]
        score = float(scores[int(chunk_index)])
        per_doc_scores[doc_id].append(score)
        best_rank.setdefault(doc_id, rank)

    features: dict[str, dict[str, float]] = {}
    ranking: list[tuple[str, float]] = []
    for doc_id, doc_scores in per_doc_scores.items():
        sorted_scores = sorted(doc_scores, reverse=True)
        max_score = sorted_scores[0]
        features[doc_id] = {
            "chunk_score": max_score,
            "chunk_rank": float(best_rank[doc_id]),
            "chunk_hit_count": float(len(sorted_scores)),
            "chunk_score_sum": float(sum(sorted_scores)),
            "chunk_top3_mean": float(sum(sorted_scores[:3]) / min(3, len(sorted_scores))),
        }
        ranking.append((doc_id, max_score + 1 / (60 + best_rank[doc_id])))
    return sorted(ranking, key=lambda item: item[1], reverse=True), features


def build_doc_token_cache(docs: list[Any]) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    for doc in docs:
        title_tokens = set(tokenize(doc.title))
        source_tokens = set(tokenize(doc.source))
        category_tokens = set(tokenize(doc.category))
        body_1400_tokens = set(tokenize(doc.body[:1400]))
        body_4000_tokens = set(tokenize(doc.body[:4000]))
        cache[doc.doc_id] = {
            "title_tokens": title_tokens,
            "source_tokens": source_tokens,
            "category_tokens": category_tokens,
            "body_1400_tokens": body_1400_tokens,
            "body_4000_tokens": body_4000_tokens,
            "all_text_lower": f"{doc.title} {doc.source} {doc.category} {doc.body[:4000]}".lower(),
            "published_years": set(re.findall(r"\b(20\d{2})\b", doc.published_at)),
            "doc_title_token_count": float(len(title_tokens)),
            "doc_body_token_count": float(len(body_4000_tokens)),
            "doc_body_char_count": float(len(doc.body)),
        }
    return cache


def overlap_ratio(query_tokens: set[str], doc_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0
    return len(query_tokens & doc_tokens) / len(query_tokens)


def build_candidate_features(
    query: str,
    vector_ranking: list[tuple[str, float]],
    bm25_ranking: list[tuple[str, float]],
    chunk_ranking: list[tuple[str, float]],
    chunk_features: dict[str, dict[str, float]],
    doc_by_id: dict[str, Any],
    doc_token_cache: dict[str, dict[str, Any]],
    aliases_by_doc: dict[str, set[str]],
    candidate_top_k: int,
) -> tuple[list[str], np.ndarray]:
    vector_scores_raw, vector_ranks = ranking_maps(vector_ranking)
    bm25_scores_raw, bm25_ranks = ranking_maps(bm25_ranking)
    chunk_scores_raw, chunk_ranks = ranking_maps(chunk_ranking)
    vector_scores = normalize_scores(vector_scores_raw)
    bm25_scores = normalize_scores(bm25_scores_raw)
    chunk_scores = normalize_scores(chunk_scores_raw)

    candidates: list[str] = []
    seen: set[str] = set()
    for ranking in [vector_ranking[:candidate_top_k], bm25_ranking[:candidate_top_k], chunk_ranking[:candidate_top_k]]:
        for doc_id, _score in ranking:
            if doc_id in seen:
                continue
            seen.add(doc_id)
            candidates.append(doc_id)

    query_tokens = set(tokenize(query))
    query_entities = [entity.lower() for entity in extract_entities(query, limit=30)]
    lowered_query = query.lower()
    years = query_years(query)
    has_source_mention = float(bool(mentioned_source_aliases(query, aliases_by_doc)))
    query_number_count = float(len(re.findall(r"\d+", query)))
    query_token_count = float(len(query_tokens))
    query_entity_count = float(len(query_entities))
    comparison_like = float(is_comparison_like(query))
    temporal_like = float(is_temporal_like(query))

    rows: list[list[float]] = []
    for doc_id in candidates:
        doc = doc_by_id[doc_id]
        cached = doc_token_cache[doc_id]
        chunk_info = chunk_features.get(doc_id, {})
        source_match = float(any(alias and alias in lowered_query for alias in aliases_by_doc[doc_id]))
        entity_title_match = 0.0
        entity_body_match = 0.0
        entity_source_match = 0.0
        if query_entities:
            title_lower = doc.title.lower()
            source_lower = doc.source.lower()
            all_text_lower = cached["all_text_lower"]
            entity_title_match = sum(1 for entity in query_entities if entity in title_lower) / len(query_entities)
            entity_body_match = sum(1 for entity in query_entities if entity in all_text_lower) / len(query_entities)
            entity_source_match = sum(1 for entity in query_entities if entity in source_lower) / len(query_entities)

        date_match = float(bool(years and years & cached["published_years"]))
        published_year_match = date_match
        rrf = (
            1 / (60 + vector_ranks.get(doc_id, 999))
            + 1 / (60 + bm25_ranks.get(doc_id, 999))
            + 1 / (60 + chunk_ranks.get(doc_id, 999))
        )

        feature_map = {
            "vector_present": float(doc_id in vector_scores_raw),
            "vector_score": vector_scores.get(doc_id, 0.0),
            "vector_rr": 1 / vector_ranks.get(doc_id, 999),
            "bm25_present": float(doc_id in bm25_scores_raw),
            "bm25_score": bm25_scores.get(doc_id, 0.0),
            "bm25_rr": 1 / bm25_ranks.get(doc_id, 999),
            "chunk_present": float(doc_id in chunk_scores_raw),
            "chunk_score": chunk_scores.get(doc_id, 0.0),
            "chunk_rr": 1 / chunk_ranks.get(doc_id, 999),
            "chunk_hit_count": chunk_info.get("chunk_hit_count", 0.0),
            "chunk_score_sum": chunk_info.get("chunk_score_sum", 0.0),
            "chunk_top3_mean": chunk_info.get("chunk_top3_mean", 0.0),
            "rrf_score": rrf,
            "source_match": source_match,
            "source_token_overlap": overlap_ratio(query_tokens, cached["source_tokens"]),
            "category_overlap": overlap_ratio(query_tokens, cached["category_tokens"]),
            "title_overlap": overlap_ratio(query_tokens, cached["title_tokens"]),
            "body_overlap_1400": overlap_ratio(query_tokens, cached["body_1400_tokens"]),
            "body_overlap_4000": overlap_ratio(query_tokens, cached["body_4000_tokens"]),
            "entity_title_match": entity_title_match,
            "entity_body_match": entity_body_match,
            "entity_source_match": entity_source_match,
            "date_match": date_match,
            "published_year_match": published_year_match,
            "query_token_count": query_token_count,
            "query_entity_count": query_entity_count,
            "query_number_count": query_number_count,
            "query_has_source_mention": has_source_mention,
            "query_is_comparison_like": comparison_like,
            "query_is_temporal_like": temporal_like,
            "doc_title_token_count": cached["doc_title_token_count"],
            "doc_body_token_count": cached["doc_body_token_count"],
            "doc_body_char_count": cached["doc_body_char_count"],
        }
        rows.append([float(feature_map[name]) for name in FEATURE_NAMES])
    return candidates, np.array(rows, dtype=np.float32)


def apply_source_coverage(
    query: str,
    ranked_doc_ids: list[str],
    scored_candidates: list[tuple[str, float]],
    doc_by_id: dict[str, Any],
    aliases_by_doc: dict[str, set[str]],
    top_k: int,
    max_insertions: int,
) -> list[str]:
    selected = list(ranked_doc_ids[:top_k])
    mentioned_aliases = mentioned_source_aliases(query, aliases_by_doc)
    if not mentioned_aliases:
        return selected

    score_by_doc = dict(scored_candidates)
    inserted = 0
    for alias in mentioned_aliases:
        if any(alias in doc_by_id[doc_id].source.lower() for doc_id in selected):
            continue
        candidate = None
        for doc_id, _score in scored_candidates:
            if alias in doc_by_id[doc_id].source.lower():
                candidate = doc_id
                break
        if candidate and candidate not in selected:
            selected[-1] = candidate
            selected = sorted(dict.fromkeys(selected), key=lambda doc_id: score_by_doc.get(doc_id, -1e9), reverse=True)
            selected = selected[:top_k]
            inserted += 1
        if inserted >= max_insertions:
            break

    for doc_id, _score in scored_candidates:
        if len(selected) >= top_k:
            break
        if doc_id not in selected:
            selected.append(doc_id)
    return selected[:top_k]


def evaluate_doc_ids(case: Any, doc_ids: list[str], doc_by_id: dict[str, Any], top_k: int) -> dict[str, float]:
    titles = [doc_by_id[doc_id].title for doc_id in doc_ids[:top_k]]
    gold_titles = set(case.gold_titles)
    return {
        "recall@5": evaluate_ranking(gold_titles, titles, 5)["recall"],
        "recall@10": evaluate_ranking(gold_titles, titles, 10)["recall"],
        "hit@10": evaluate_ranking(gold_titles, titles, 10)["hit"],
        "mrr@10": evaluate_ranking(gold_titles, titles, 10)["mrr"],
        "ndcg@10": evaluate_ranking(gold_titles, titles, 10)["ndcg"],
    }


def summarize(rows: list[dict[str, Any]], modes: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for mode in modes:
        mode_rows = [row["metrics"][mode] for row in rows]
        summary[mode] = {
            "recall_at_5": round(sum(row["recall@5"] for row in mode_rows) / len(mode_rows), 4),
            "recall_at_10": round(sum(row["recall@10"] for row in mode_rows) / len(mode_rows), 4),
            "hit_at_10": round(sum(row["hit@10"] for row in mode_rows) / len(mode_rows), 4),
            "mrr_at_10": round(sum(row["mrr@10"] for row in mode_rows) / len(mode_rows), 4),
            "ndcg_at_10": round(sum(row["ndcg@10"] for row in mode_rows) / len(mode_rows), 4),
        }
    vector = summary["vector_only"]
    summary["relative_lifts"] = {}
    for mode in modes:
        if mode == "vector_only":
            continue
        summary["relative_lifts"][f"{mode}_vs_vector_recall_at_10"] = round(
            (summary[mode]["recall_at_10"] - vector["recall_at_10"]) / vector["recall_at_10"],
            4,
        )
    return summary


def train_ranker(
    feature_rows: list[np.ndarray],
    labels: list[np.ndarray],
    train_count: int,
    args: argparse.Namespace,
) -> lgb.LGBMRanker:
    x_train = np.vstack(feature_rows[:train_count])
    y_train = np.concatenate(labels[:train_count])
    group = [len(row) for row in feature_rows[:train_count]]
    ranker = lgb.LGBMRanker(
        objective="lambdarank",
        metric="ndcg",
        boosting_type="gbdt",
        n_estimators=args.n_estimators,
        learning_rate=args.learning_rate,
        num_leaves=args.num_leaves,
        max_depth=args.max_depth,
        min_child_samples=args.min_child_samples,
        subsample=args.subsample,
        colsample_bytree=args.colsample_bytree,
        reg_lambda=args.reg_lambda,
        random_state=args.seed,
        n_jobs=-1,
        verbosity=-1,
    )
    ranker.fit(x_train, y_train, group=group)
    return ranker


def generate_report(run_id: str, config: dict[str, Any], metrics: dict[str, Any], result_dir: Path) -> None:
    modes = config["modes"]
    rows = []
    for mode in modes:
        item = metrics["holdout"][mode]
        rows.append(
            f"| {mode} | {item['recall_at_5']:.2%} | {item['recall_at_10']:.2%} | "
            f"{item['hit_at_10']:.2%} | {item['mrr_at_10']:.2%} | {item['ndcg_at_10']:.2%} |"
        )
    best_lift = metrics["holdout"]["relative_lifts"].get("lambdamart_source_coverage_vs_vector_recall_at_10")
    status = "达到 20% 严格 holdout 提升" if best_lift is not None and best_lift >= 0.20 else "未达到 20% 严格 holdout 提升"
    best_lift_text = "N/A" if best_lift is None else f"{best_lift:.2%}"

    report = f"""# MultiHop-RAG LambdaMART 重排序实验

## 结论

- 运行编号：`{run_id}`
- 数据集：MultiHop-RAG 官方数据，跳过 `null_query` 后共 `{config['case_count']}` 条可评估 query
- 训练集：`{config['train_size']}` 条
- Dev 集：`{config['dev_size']}` 条
- Holdout 集：`{config['holdout_size']}` 条
- 主指标：`Recall@10`
- 结果：{status}
- Holdout 最佳相对提升：`{best_lift_text}`
- 结果目录：`{result_dir}`

## 实验方法

本实验使用 LightGBM LambdaMART 学习排序模型，在文档级向量、BM25、chunk 级向量三路召回组成的候选集上进行重排序。MultiHop-RAG 的金标证据标题只用于训练集内的排序标签，以及 holdout 上的最终评分；holdout 不参与模型拟合。

## 特征

特征列表：

```json
{json.dumps(FEATURE_NAMES, ensure_ascii=False, indent=2)}
```

## Holdout 结果

| 模式 | Recall@5 | Recall@10 | Hit@10 | MRR@10 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

相对 `vector_only` 的提升：

```json
{json.dumps(metrics['holdout']['relative_lifts'], ensure_ascii=False, indent=2)}
```

## 复现命令

```bash
conda run -n rag python evals/rag/run_multihop_lambdamart_eval.py --query-limit {config['requested_query_limit']} --train-size {config['train_size']} --dev-size {config['dev_size']} --candidate-top-k {config['candidate_top_k']} --chunk-top-k {config['chunk_top_k']} --num-leaves {config['num_leaves']} --n-estimators {config['n_estimators']}
```
"""
    (PROJECT_ROOT / "evals" / "reports" / "multihop_rag_lambdamart_evaluation.md").write_text(
        report,
        encoding="utf-8",
    )


async def main_async(args: argparse.Namespace) -> int:
    ensure_dirs()
    run_id = args.run_id or datetime.now(timezone.utc).strftime("rag_lambdamart_%Y%m%dT%H%M%SZ")
    result_dir = PROJECT_ROOT / "evals" / "results" / "rag" / run_id
    result_dir.mkdir(parents=True, exist_ok=True)

    raw_qa, raw_corpus = load_multihop_data()
    docs = build_corpus(raw_corpus)
    doc_by_id = {doc.doc_id: doc for doc in docs}
    title_to_doc = {doc.title: doc for doc in docs}
    cases = build_query_cases(raw_qa, set(title_to_doc), args.query_limit, args.seed)
    if args.train_size + args.dev_size >= len(cases):
        raise ValueError("train_size + dev_size must leave a non-empty holdout split")

    bm25_index = build_bm25_index(docs)
    aliases_by_doc = build_source_aliases(docs)
    doc_token_cache = build_doc_token_cache(docs)

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

    feature_rows: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    candidate_doc_ids: list[list[str]] = []
    base_rows: list[dict[str, Any]] = []

    for index, (case, query_embedding, query_vector) in enumerate(zip(cases, query_embeddings, query_matrix), start=1):
        vector_ranking = search_milvus(milvus, args.collection, query_embedding, args.candidate_top_k)
        bm25_ranking = bm25_rank(case.query, docs, bm25_index, top_k=args.candidate_top_k)
        chunk_ranking, chunk_features = enriched_chunk_doc_features(
            query_vector,
            chunk_matrix,
            chunks,
            args.chunk_top_k,
        )
        candidates, features = build_candidate_features(
            case.query,
            vector_ranking,
            bm25_ranking,
            chunk_ranking,
            chunk_features,
            doc_by_id,
            doc_token_cache,
            aliases_by_doc,
            args.candidate_top_k,
        )
        gold_titles = set(case.gold_titles)
        label = np.array([1 if doc_by_id[doc_id].title in gold_titles else 0 for doc_id in candidates], dtype=np.int32)
        feature_rows.append(features)
        labels.append(label)
        candidate_doc_ids.append(candidates)

        chunk_doc_ids = [doc_id for doc_id, _score in chunk_ranking[: args.top_k]]
        vector_doc_ids = [doc_id for doc_id, _score in vector_ranking[: args.top_k]]
        bm25_doc_ids = [doc_id for doc_id, _score in bm25_ranking[: args.top_k]]
        base_rows.append(
            {
                "case": asdict(case),
                "metrics": {
                    "vector_only": evaluate_doc_ids(case, vector_doc_ids, doc_by_id, args.top_k),
                    "bm25_only": evaluate_doc_ids(case, bm25_doc_ids, doc_by_id, args.top_k),
                    "chunk_vector": evaluate_doc_ids(case, chunk_doc_ids, doc_by_id, args.top_k),
                },
                "rankings": {
                    "vector_only": vector_doc_ids[: args.top_k],
                    "bm25_only": bm25_doc_ids[: args.top_k],
                    "chunk_vector": chunk_doc_ids[: args.top_k],
                },
            }
        )
        if index % 25 == 0 or index == len(cases):
            print(f"features {index}/{len(cases)}", flush=True)

    ranker = train_ranker(feature_rows, labels, args.train_size, args)
    modes = ["vector_only", "bm25_only", "chunk_vector", "lambdamart", "lambdamart_source_coverage"]
    all_rows: list[dict[str, Any]] = []

    for index, case in enumerate(cases):
        features = feature_rows[index]
        candidates = candidate_doc_ids[index]
        scores = ranker.predict(features)
        scored_candidates = sorted(zip(candidates, [float(score) for score in scores]), key=lambda item: item[1], reverse=True)
        lambdamart_doc_ids = [doc_id for doc_id, _score in scored_candidates[: args.top_k]]
        coverage_doc_ids = apply_source_coverage(
            case.query,
            lambdamart_doc_ids,
            scored_candidates,
            doc_by_id,
            aliases_by_doc,
            args.top_k,
            args.max_source_insertions,
        )
        row = base_rows[index]
        row["metrics"]["lambdamart"] = evaluate_doc_ids(case, lambdamart_doc_ids, doc_by_id, args.top_k)
        row["metrics"]["lambdamart_source_coverage"] = evaluate_doc_ids(case, coverage_doc_ids, doc_by_id, args.top_k)
        row["rankings"]["lambdamart"] = lambdamart_doc_ids
        row["rankings"]["lambdamart_source_coverage"] = coverage_doc_ids
        all_rows.append(row)

    train_rows = all_rows[: args.train_size]
    dev_rows = all_rows[args.train_size : args.train_size + args.dev_size]
    holdout_rows = all_rows[args.train_size + args.dev_size :]
    metrics = {
        "train": summarize(train_rows, modes),
        "dev": summarize(dev_rows, modes) if dev_rows else {},
        "holdout": summarize(holdout_rows, modes),
        "by_question_type_holdout": {},
    }
    holdout_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in holdout_rows:
        holdout_by_type[row["case"]["question_type"]].append(row)
    metrics["by_question_type_holdout"] = {
        question_type: summarize(rows, modes) for question_type, rows in holdout_by_type.items()
    }

    config = {
        "run_id": run_id,
        "seed": args.seed,
        "requested_query_limit": args.query_limit,
        "case_count": len(cases),
        "train_size": args.train_size,
        "dev_size": args.dev_size,
        "holdout_size": len(holdout_rows),
        "top_k": args.top_k,
        "candidate_top_k": args.candidate_top_k,
        "chunk_top_k": args.chunk_top_k,
        "chunk_size": args.chunk_size,
        "chunk_overlap": args.chunk_overlap,
        "collection": args.collection,
        "embedding_model": settings.ollama.embedding_model,
        "embedding_dim": EMBED_DIM,
        "feature_names": FEATURE_NAMES,
        "modes": modes,
        "num_leaves": args.num_leaves,
        "n_estimators": args.n_estimators,
        "learning_rate": args.learning_rate,
        "max_source_insertions": args.max_source_insertions,
    }
    write_json(result_dir / "config.json", config)
    write_json(result_dir / "metrics.json", metrics)
    write_jsonl(result_dir / "raw_rankings.jsonl", all_rows)
    generate_report(run_id, config, metrics, result_dir)
    print(json.dumps({"run_id": run_id, "holdout": metrics["holdout"]}, ensure_ascii=False, indent=2), flush=True)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate LightGBM LambdaMART rerank on MultiHop-RAG.")
    parser.add_argument("--query-limit", type=int, default=2556)
    parser.add_argument("--train-size", type=int, default=1500)
    parser.add_argument("--dev-size", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--candidate-top-k", type=int, default=100)
    parser.add_argument("--chunk-top-k", type=int, default=400)
    parser.add_argument("--chunk-size", type=int, default=2500)
    parser.add_argument("--chunk-overlap", type=int, default=400)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--embed-batch-size", type=int, default=16)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--n-estimators", type=int, default=650)
    parser.add_argument("--learning-rate", type=float, default=0.035)
    parser.add_argument("--num-leaves", type=int, default=63)
    parser.add_argument("--max-depth", type=int, default=-1)
    parser.add_argument("--min-child-samples", type=int, default=12)
    parser.add_argument("--subsample", type=float, default=0.9)
    parser.add_argument("--colsample-bytree", type=float, default=0.9)
    parser.add_argument("--reg-lambda", type=float, default=0.5)
    parser.add_argument("--max-source-insertions", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    return asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
