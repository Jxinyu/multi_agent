from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import re
import sys
import time
import urllib.request
import calendar
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase
from ollama import Client as OllamaClient
from pymilvus import MilvusClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402


MULTIHOP_QA_URL = "https://media.githubusercontent.com/media/yixuantt/MultiHop-RAG/main/dataset/MultiHopRAG.json"
MULTIHOP_CORPUS_URL = "https://media.githubusercontent.com/media/yixuantt/MultiHop-RAG/main/dataset/corpus.json"
DEFAULT_DATASET_ID = "multihop_rag_eval_v1"
DEFAULT_COLLECTION = "eval_multihop_rag_docs"
DEFAULT_SEED = 20260706
EMBED_DIM = settings.milvus.dims
RRF_K = 60
TUNING_SIZE = 200

STOPWORDS = {
    "a",
    "about",
    "after",
    "all",
    "also",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "both",
    "but",
    "by",
    "can",
    "for",
    "from",
    "had",
    "has",
    "have",
    "how",
    "in",
    "into",
    "is",
    "it",
    "its",
    "more",
    "new",
    "not",
    "of",
    "on",
    "or",
    "over",
    "reported",
    "that",
    "the",
    "their",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
}


@dataclass(frozen=True)
class CorpusDoc:
    doc_id: str
    title: str
    source: str
    category: str
    published_at: str
    body: str


@dataclass(frozen=True)
class QueryCase:
    case_id: str
    query: str
    answer: str
    question_type: str
    gold_titles: list[str]


@dataclass(frozen=True)
class SourceIndex:
    aliases_by_doc: dict[str, set[str]]
    known_aliases: set[str]


def ensure_dirs() -> None:
    for path in [
        PROJECT_ROOT / "evals" / "data" / "rag",
        PROJECT_ROOT / "evals" / "results" / "rag",
        PROJECT_ROOT / "evals" / "reports",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def download_file(url: str, path: Path) -> None:
    if path.exists():
        return
    with urllib.request.urlopen(url, timeout=180) as response:
        path.write_bytes(response.read())


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_multihop_data() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ensure_dirs()
    data_dir = PROJECT_ROOT / "evals" / "data" / "rag"
    qa_path = data_dir / "MultiHopRAG.json"
    corpus_path = data_dir / "corpus.json"
    download_file(MULTIHOP_QA_URL, qa_path)
    download_file(MULTIHOP_CORPUS_URL, corpus_path)
    return load_json(qa_path), load_json(corpus_path)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_'-]{1,}", text.lower())
        if token not in STOPWORDS and len(token) > 2
    ]


def extract_entities(text: str, limit: int = 12) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r"\b(?:[A-Z][a-zA-Z0-9&.'-]*\s+){0,4}[A-Z][a-zA-Z0-9&.'-]*\b", text):
        phrase = normalize_text(match.group(0))
        if len(phrase) < 3:
            continue
        lowered = phrase.lower()
        if lowered in STOPWORDS:
            continue
        if phrase not in candidates:
            candidates.append(phrase)
    return candidates[:limit]


def build_source_index(docs: list[CorpusDoc]) -> SourceIndex:
    aliases_by_doc: dict[str, set[str]] = {}
    known_aliases: set[str] = set()
    for doc in docs:
        source = doc.source.lower()
        aliases = {source}
        for part in re.split(r"\||-|/", source):
            alias = normalize_text(part).lower()
            if len(alias) >= 3:
                aliases.add(alias)
                known_aliases.add(alias)
        if "cnbc" in source:
            aliases.add("cnbc")
            known_aliases.add("cnbc")
        aliases_by_doc[doc.doc_id] = aliases
    return SourceIndex(aliases_by_doc=aliases_by_doc, known_aliases=known_aliases)


def mentioned_source_count(query: str, source_index: SourceIndex) -> int:
    lowered = query.lower()
    return sum(1 for alias in source_index.known_aliases if alias in lowered)


def is_comparison_like_query(query: str) -> bool:
    return bool(
        re.search(
            r"\b(compare|compared|comparison|while|whereas|both|same|different|difference|whether|does|do|between)\b",
            query,
            flags=re.IGNORECASE,
        )
    )


def query_dates(query: str) -> set[str]:
    dates = set(re.findall(r"20\d{2}-\d{1,2}-\d{1,2}", query))
    month_lookup = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
    month_lookup.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
    for month_name, day, year in re.findall(r"\b([A-Z][a-z]+)\s+(\d{1,2}),\s*(20\d{2})", query):
        month_number = month_lookup.get(month_name.lower())
        if month_number:
            dates.add(f"{year}-{month_number:02d}-{int(day):02d}")
    return dates


def normalize_scores(items: dict[str, float]) -> dict[str, float]:
    if not items:
        return {}
    min_value = min(items.values())
    max_value = max(items.values())
    if max_value == min_value:
        return {key: 1.0 for key in items}
    return {key: (value - min_value) / (max_value - min_value) for key, value in items.items()}


def build_corpus(raw_corpus: list[dict[str, Any]]) -> list[CorpusDoc]:
    docs: list[CorpusDoc] = []
    for index, item in enumerate(raw_corpus):
        docs.append(
            CorpusDoc(
                doc_id=f"doc_{index:04d}",
                title=normalize_text(item.get("title", "")),
                source=normalize_text(item.get("source", "")),
                category=normalize_text(item.get("category", "")),
                published_at=normalize_text(item.get("published_at", "")),
                body=normalize_text(item.get("body", "")),
            )
        )
    return docs


def build_query_cases(raw_qa: list[dict[str, Any]], corpus_titles: set[str], limit: int, seed: int) -> list[QueryCase]:
    candidates: list[QueryCase] = []
    for index, item in enumerate(raw_qa):
        if item.get("question_type") == "null_query":
            continue
        gold_titles = []
        for evidence in item.get("evidence_list", []):
            title = normalize_text(evidence.get("title", ""))
            if title and title in corpus_titles and title not in gold_titles:
                gold_titles.append(title)
        if not gold_titles:
            continue
        candidates.append(
            QueryCase(
                case_id=f"mh_{index:04d}",
                query=normalize_text(item.get("query", "")),
                answer=normalize_text(item.get("answer", "")),
                question_type=normalize_text(item.get("question_type", "")),
                gold_titles=gold_titles,
            )
        )
    rng = random.Random(seed)
    rng.shuffle(candidates)
    return candidates[:limit]


def build_bm25_index(docs: list[CorpusDoc]) -> dict[str, Any]:
    term_freqs: dict[str, Counter[str]] = {}
    doc_lengths: dict[str, int] = {}
    doc_freq: Counter[str] = Counter()
    for doc in docs:
        tokens = tokenize(f"{doc.title} {doc.source} {doc.category} {doc.body[:4000]}")
        counts = Counter(tokens)
        term_freqs[doc.doc_id] = counts
        doc_lengths[doc.doc_id] = sum(counts.values())
        for token in counts:
            doc_freq[token] += 1
    avgdl = sum(doc_lengths.values()) / len(doc_lengths)
    return {"term_freqs": term_freqs, "doc_lengths": doc_lengths, "doc_freq": doc_freq, "avgdl": avgdl}


def bm25_rank(query: str, docs: list[CorpusDoc], index: dict[str, Any], top_k: int) -> list[tuple[str, float]]:
    query_terms = tokenize(query)
    scores: dict[str, float] = defaultdict(float)
    total_docs = len(docs)
    k1 = 1.5
    b = 0.75
    for term in query_terms:
        df = index["doc_freq"].get(term, 0)
        if df == 0:
            continue
        idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
        for doc in docs:
            tf = index["term_freqs"][doc.doc_id].get(term, 0)
            if tf == 0:
                continue
            dl = index["doc_lengths"][doc.doc_id] or 1
            denom = tf + k1 * (1 - b + b * dl / index["avgdl"])
            scores[doc.doc_id] += idf * (tf * (k1 + 1) / denom)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]


def embed_texts(texts: list[str], cache_path: Path, batch_size: int) -> list[list[float]]:
    if cache_path.exists():
        cached = load_json(cache_path)
        if len(cached) == len(texts):
            return cached
    client = OllamaClient(host=settings.ollama.base_url)
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        response = client.embed(
            model=settings.ollama.embedding_model,
            input=batch,
            dimensions=EMBED_DIM,
        )
        embeddings.extend(response["embeddings"])
        print(f"embedded {min(start + batch_size, len(texts))}/{len(texts)}", flush=True)
    write_json(cache_path, embeddings)
    return embeddings


def prepare_milvus(
    docs: list[CorpusDoc],
    collection_name: str,
    rebuild: bool,
    batch_size: int,
) -> MilvusClient:
    data_dir = PROJECT_ROOT / "evals" / "data" / "rag"
    embedding_path = data_dir / f"corpus_embeddings_{settings.ollama.embedding_model.replace(':', '_')}_{EMBED_DIM}.json"
    texts = [f"{doc.title}\nSource: {doc.source}\nCategory: {doc.category}\n\n{doc.body[:5000]}" for doc in docs]
    embeddings = embed_texts(texts, embedding_path, batch_size)

    client = MilvusClient(uri=settings.milvus.uri)
    if rebuild and client.has_collection(collection_name):
        client.drop_collection(collection_name)
    if not client.has_collection(collection_name):
        client.create_collection(
            collection_name=collection_name,
            dimension=EMBED_DIM,
            primary_field_name="id",
            vector_field_name="embedding",
            metric_type="COSINE",
            auto_id=False,
        )
        rows = []
        for doc, embedding in zip(docs, embeddings):
            rows.append(
                {
                    "id": int(doc.doc_id.rsplit("_", 1)[1]),
                    "doc_id": doc.doc_id,
                    "embedding": embedding,
                    "title": doc.title,
                    "source": doc.source,
                    "category": doc.category,
                }
            )
        for start in range(0, len(rows), 100):
            client.insert(collection_name=collection_name, data=rows[start : start + 100])
        client.flush(collection_name)
    return client


def prepare_neo4j(docs: list[CorpusDoc], dataset_id: str, rebuild: bool) -> None:
    driver = GraphDatabase.driver(settings.neo4j.url, auth=(settings.neo4j.username, settings.neo4j.password))
    try:
        with driver.session() as session:
            if rebuild:
                session.run("MATCH (d:EvalMultiHopDoc {dataset_id: $dataset_id}) DETACH DELETE d", dataset_id=dataset_id)
                session.run("MATCH (e:EvalMultiHopEntity {dataset_id: $dataset_id}) DETACH DELETE e", dataset_id=dataset_id)
            count = session.run(
                "MATCH (d:EvalMultiHopDoc {dataset_id: $dataset_id}) RETURN count(d) AS count",
                dataset_id=dataset_id,
            ).single()["count"]
            if count == len(docs):
                return
            session.run("CREATE CONSTRAINT eval_multihop_doc IF NOT EXISTS FOR (d:EvalMultiHopDoc) REQUIRE d.doc_id IS UNIQUE")
            session.run(
                "CREATE CONSTRAINT eval_multihop_entity IF NOT EXISTS FOR (e:EvalMultiHopEntity) REQUIRE e.entity_key IS UNIQUE"
            )
            for doc in docs:
                entities = extract_entities(f"{doc.title}. {doc.body[:1200]}", limit=12)
                session.run(
                    """
                    MERGE (d:EvalMultiHopDoc {doc_id: $doc_id})
                    SET d.dataset_id = $dataset_id,
                        d.title = $title,
                        d.source = $source,
                        d.category = $category
                    WITH d
                    UNWIND $entities AS entity
                    MERGE (e:EvalMultiHopEntity {entity_key: $dataset_id + '|' + toLower(entity)})
                    SET e.dataset_id = $dataset_id,
                        e.name = entity
                    MERGE (d)-[:HAS_ENTITY]->(e)
                    """,
                    dataset_id=dataset_id,
                    doc_id=doc.doc_id,
                    title=doc.title,
                    source=doc.source,
                    category=doc.category,
                    entities=entities,
                )
    finally:
        driver.close()


def search_milvus(
    client: MilvusClient,
    collection_name: str,
    query_embedding: list[float],
    top_k: int,
) -> list[tuple[str, float]]:
    results = client.search(
        collection_name=collection_name,
        data=[query_embedding],
        limit=top_k,
        output_fields=["doc_id", "title"],
    )
    ranking: list[tuple[str, float]] = []
    for hit in results[0]:
        entity = hit.get("entity") or {}
        doc_id = entity.get("doc_id") or f"doc_{int(hit['id']):04d}"
        ranking.append((doc_id, float(hit.get("distance", 0.0))))
    return ranking


def load_neo4j_adjacency(dataset_id: str) -> dict[str, dict[str, int]]:
    adjacency: dict[str, dict[str, int]] = defaultdict(dict)
    driver = GraphDatabase.driver(settings.neo4j.url, auth=(settings.neo4j.username, settings.neo4j.password))
    try:
        with driver.session() as session:
            rows = session.run(
                """
                MATCH (d:EvalMultiHopDoc {dataset_id: $dataset_id})-[:HAS_ENTITY]->(e:EvalMultiHopEntity)
                      <-[:HAS_ENTITY]-(n:EvalMultiHopDoc {dataset_id: $dataset_id})
                WHERE d.doc_id <> n.doc_id
                RETURN d.doc_id AS doc_id, n.doc_id AS neighbor_id, count(DISTINCT e) AS shared
                """,
                dataset_id=dataset_id,
            )
            for row in rows:
                adjacency[row["doc_id"]][row["neighbor_id"]] = int(row["shared"] or 0)
    finally:
        driver.close()
    return adjacency


def graph_expand(
    seed_scores: list[tuple[str, float]],
    doc_by_id: dict[str, CorpusDoc],
    adjacency: dict[str, dict[str, int]],
    top_k: int,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = defaultdict(float)
    seed_ids = [doc_id for doc_id, _score in seed_scores]
    seed_score_map = {doc_id: score for doc_id, score in seed_scores}
    for rank, (doc_id, score) in enumerate(seed_scores, start=1):
        scores[doc_id] += score + (1.0 / (RRF_K + rank))

    for seed_id in seed_ids:
        for doc_id, shared in adjacency.get(seed_id, {}).items():
            scores[doc_id] += seed_score_map.get(seed_id, 0.0) * min(0.8, 0.18 * shared)

    # Metadata graph expansion: docs from the same source/category get a small boost.
    for seed_id, seed_score in seed_scores[:8]:
        seed_doc = doc_by_id[seed_id]
        for doc in doc_by_id.values():
            if doc.doc_id == seed_id:
                continue
            if doc.source and doc.source == seed_doc.source:
                scores[doc.doc_id] += seed_score * 0.08
            if doc.category and doc.category == seed_doc.category:
                scores[doc.doc_id] += seed_score * 0.03

    return sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]


def rrf_fuse(rankings: list[list[tuple[str, float]]], weights: list[float], top_k: int) -> list[tuple[str, float]]:
    scores: dict[str, float] = defaultdict(float)
    for ranking, weight in zip(rankings, weights):
        for rank, (doc_id, _score) in enumerate(ranking, start=1):
            scores[doc_id] += weight / (RRF_K + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]


def vector_preserving_hybrid(
    vector_ranking: list[tuple[str, float]],
    graph_ranking: list[tuple[str, float]],
    top_k: int,
) -> list[tuple[str, float]]:
    """Keep strong vector results while reserving tail slots for graph-only evidence candidates."""
    if top_k <= 10:
        preserve = max(1, top_k - 2)
        supplement = top_k - preserve
    else:
        preserve = 8
        supplement = 2

    merged: list[tuple[str, float]] = []
    seen: set[str] = set()
    for doc_id, score in vector_ranking[:preserve]:
        merged.append((doc_id, score + 1.0))
        seen.add(doc_id)
    for doc_id, score in graph_ranking:
        if doc_id in seen:
            continue
        merged.append((doc_id, score * 0.5))
        seen.add(doc_id)
        supplement -= 1
        if supplement <= 0:
            break
    for doc_id, score in rrf_fuse([vector_ranking, graph_ranking], weights=[1.0, 0.35], top_k=top_k * 2):
        if doc_id in seen:
            continue
        merged.append((doc_id, score))
        seen.add(doc_id)
        if len(merged) >= top_k:
            break
    return merged[:top_k]


def metadata_graph_rerank(
    query: str,
    vector_ranking: list[tuple[str, float]],
    bm25_ranking: list[tuple[str, float]],
    doc_by_id: dict[str, CorpusDoc],
    source_index: SourceIndex,
    top_k: int,
    adaptive: bool = False,
) -> list[tuple[str, float]]:
    candidates: list[str] = []
    seen: set[str] = set()
    for ranking in [vector_ranking, bm25_ranking]:
        for doc_id, _score in ranking:
            if doc_id in seen:
                continue
            seen.add(doc_id)
            candidates.append(doc_id)

    vector_rank = {doc_id: rank for rank, (doc_id, _score) in enumerate(vector_ranking, start=1)}
    bm25_rank_map = {doc_id: rank for rank, (doc_id, _score) in enumerate(bm25_ranking, start=1)}
    vector_scores = normalize_scores(dict(vector_ranking))
    bm25_scores = normalize_scores(dict(bm25_ranking))

    lowered_query = query.lower()
    query_tokens = set(tokenize(query))
    query_entities = [entity.lower() for entity in extract_entities(query, limit=30)]
    dates = query_dates(query)

    general_weights = {
        "vector_score": 1.5,
        "vector_rank": 0.1,
        "bm25_score": 0.5,
        "bm25_rank": 0.05,
        "source_match": 2.0,
        "entity_match": 1.0,
        "title_overlap": 0.5,
        "body_overlap": 0.1,
        "date_match": 0.0,
    }
    comparison_weights = {
        "vector_score": 1.0,
        "vector_rank": 0.1,
        "bm25_score": 2.0,
        "bm25_rank": 0.05,
        "source_match": 3.0,
        "entity_match": 0.5,
        "title_overlap": 0.0,
        "body_overlap": 0.1,
        "date_match": 0.0,
    }
    weights = comparison_weights if adaptive and is_comparison_like_query(query) else general_weights

    scored: list[tuple[str, float]] = []
    for doc_id in candidates:
        doc = doc_by_id[doc_id]
        doc_text = f"{doc.title} {doc.source} {doc.category} {doc.body[:1800]}".lower()
        title_tokens = set(tokenize(doc.title))
        body_tokens = set(tokenize(doc.body[:1400]))
        source_match = 1.0 if any(alias and alias in lowered_query for alias in source_index.aliases_by_doc[doc_id]) else 0.0
        entity_match = sum(1 for entity in query_entities if entity and entity in doc_text) / max(1, len(query_entities))
        title_overlap = len(query_tokens & title_tokens) / max(1, len(query_tokens))
        body_overlap = len(query_tokens & body_tokens) / max(1, len(query_tokens))
        date_match = 1.0 if dates and doc.published_at[:10] in dates else 0.0
        features = {
            "vector_score": vector_scores.get(doc_id, 0.0),
            "vector_rank": 1 / vector_rank.get(doc_id, 999),
            "bm25_score": bm25_scores.get(doc_id, 0.0),
            "bm25_rank": 1 / bm25_rank_map.get(doc_id, 999),
            "source_match": source_match,
            "entity_match": entity_match,
            "title_overlap": title_overlap,
            "body_overlap": body_overlap,
            "date_match": date_match,
        }
        score = sum(weights[name] * value for name, value in features.items())
        scored.append((doc_id, score))

    return sorted(scored, key=lambda item: item[1], reverse=True)[:top_k]


def evaluate_ranking(gold_titles: set[str], ranking_titles: list[str], k: int) -> dict[str, float]:
    top = ranking_titles[:k]
    hits = [1 if title in gold_titles else 0 for title in top]
    hit_count = sum(hits)
    recall = hit_count / len(gold_titles) if gold_titles else 0.0
    hit_at_k = 1.0 if hit_count > 0 else 0.0
    mrr = 0.0
    for rank, hit in enumerate(hits, start=1):
        if hit:
            mrr = 1.0 / rank
            break
    dcg = sum(hit / math.log2(rank + 1) for rank, hit in enumerate(hits, start=1))
    ideal_hits = [1] * min(len(gold_titles), k)
    idcg = sum(hit / math.log2(rank + 1) for rank, hit in enumerate(ideal_hits, start=1))
    ndcg = dcg / idcg if idcg else 0.0
    return {"recall": recall, "hit": hit_at_k, "mrr": mrr, "ndcg": ndcg}


def aggregate_metrics(per_case: list[dict[str, Any]], modes: list[str]) -> dict[str, Any]:
    def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for mode in modes:
            mode_rows = [row["metrics"][mode] for row in rows]
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
        return summary

    metrics: dict[str, Any] = summarize(per_case)
    for mode in modes:
        if mode == "vector_only" or mode not in metrics:
            continue
        vector = metrics.get("vector_only", {})
        target = metrics[mode]
        if vector.get("recall_at_10"):
            metrics.setdefault("relative_lifts", {})[f"{mode}_vs_vector_recall_at_10"] = round(
                (target["recall_at_10"] - vector["recall_at_10"]) / vector["recall_at_10"],
                4,
            )
        else:
            metrics.setdefault("relative_lifts", {})[f"{mode}_vs_vector_recall_at_10"] = None

    dev_rows = per_case[: min(TUNING_SIZE, len(per_case))]
    holdout_rows = per_case[min(TUNING_SIZE, len(per_case)) :]
    metrics["splits"] = {
        "dev_first_200": summarize(dev_rows),
        "holdout_after_200": summarize(holdout_rows) if holdout_rows else {},
    }
    for split_name, split_metrics in metrics["splits"].items():
        if not split_metrics:
            continue
        vector = split_metrics.get("vector_only", {})
        split_metrics["relative_lifts"] = {}
        for mode in modes:
            if mode == "vector_only" or mode not in split_metrics:
                continue
            if vector.get("recall_at_10"):
                split_metrics["relative_lifts"][f"{mode}_vs_vector_recall_at_10"] = round(
                    (split_metrics[mode]["recall_at_10"] - vector["recall_at_10"]) / vector["recall_at_10"],
                    4,
                )
            else:
                split_metrics["relative_lifts"][f"{mode}_vs_vector_recall_at_10"] = None

    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in per_case:
        by_type[row["case"]["question_type"]].append(row)
    metrics["by_question_type"] = {}
    for question_type, rows in by_type.items():
        type_metrics = summarize(rows)
        vector = type_metrics.get("vector_only", {})
        type_metrics["relative_lifts"] = {}
        for mode in modes:
            if mode == "vector_only" or mode not in type_metrics:
                continue
            if vector.get("recall_at_10"):
                type_metrics["relative_lifts"][f"{mode}_vs_vector_recall_at_10"] = round(
                    (type_metrics[mode]["recall_at_10"] - vector["recall_at_10"]) / vector["recall_at_10"],
                    4,
                )
            else:
                type_metrics["relative_lifts"][f"{mode}_vs_vector_recall_at_10"] = None
        metrics["by_question_type"][question_type] = type_metrics

    if holdout_rows:
        holdout_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in holdout_rows:
            holdout_by_type[row["case"]["question_type"]].append(row)
        metrics["holdout_by_question_type"] = {}
        for question_type, rows in holdout_by_type.items():
            type_metrics = summarize(rows)
            vector = type_metrics.get("vector_only", {})
            type_metrics["relative_lifts"] = {}
            for mode in modes:
                if mode == "vector_only" or mode not in type_metrics:
                    continue
                if vector.get("recall_at_10"):
                    type_metrics["relative_lifts"][f"{mode}_vs_vector_recall_at_10"] = round(
                        (type_metrics[mode]["recall_at_10"] - vector["recall_at_10"]) / vector["recall_at_10"],
                        4,
                    )
                else:
                    type_metrics["relative_lifts"][f"{mode}_vs_vector_recall_at_10"] = None
            metrics["holdout_by_question_type"][question_type] = type_metrics

    vector = metrics.get("vector_only", {})
    hybrid = metrics.get("hybrid_rrf", {})
    if vector.get("recall_at_10"):
        metrics.setdefault("relative_lifts", {})["hybrid_rrf_vs_vector_recall_at_10"] = round(
                (hybrid["recall_at_10"] - vector["recall_at_10"]) / vector["recall_at_10"],
                4,
            )
    else:
        metrics.setdefault("relative_lifts", {})["hybrid_rrf_vs_vector_recall_at_10"] = None
    return metrics


def generate_report(
    run_id: str,
    cases: list[QueryCase],
    metrics: dict[str, Any],
    config: dict[str, Any],
) -> None:
    report_path = PROJECT_ROOT / "evals" / "reports" / "multihop_rag_retrieval_evaluation.md"
    lift = metrics.get("relative_lifts", {}).get("adaptive_graph_rerank_vs_vector_recall_at_10")
    comparison_holdout_lift = (
        metrics.get("holdout_by_question_type", {})
        .get("comparison_query", {})
        .get("relative_lifts", {})
        .get("adaptive_graph_rerank_vs_vector_recall_at_10")
    )
    status = "未达到 20% 相对提升"
    if lift is not None and lift >= 0.20:
        status = "达到 20% 相对提升"
    comparison_status = "未达到 20% 相对提升"
    if comparison_holdout_lift is not None and comparison_holdout_lift >= 0.20:
        comparison_status = "达到 20% 相对提升"

    rows = []
    for mode in ["vector_only", "bm25_only", "graph_only", "hybrid_rrf", "metadata_graph_rerank", "adaptive_graph_rerank"]:
        item = metrics[mode]
        rows.append(
            "| {mode} | {r5:.2%} | {r10:.2%} | {hit:.2%} | {mrr:.2%} | {ndcg:.2%} | {latency} |".format(
                mode=mode,
                r5=item["recall_at_5"],
                r10=item["recall_at_10"],
                hit=item["hit_at_10"],
                mrr=item["mrr_at_10"],
                ndcg=item["ndcg_at_10"],
                latency=item["avg_latency_seconds"],
            )
        )

    question_types = Counter(case.question_type for case in cases)
    by_type_payload = {
        question_type: {
            mode: values[mode]["recall_at_10"]
            for mode in ["vector_only", "metadata_graph_rerank", "adaptive_graph_rerank"]
            if mode in values
        }
        | {"relative_lifts": values.get("relative_lifts", {})}
        for question_type, values in metrics.get("by_question_type", {}).items()
    }
    holdout_payload = {
        question_type: {
            mode: values[mode]["recall_at_10"]
            for mode in ["vector_only", "metadata_graph_rerank", "adaptive_graph_rerank"]
            if mode in values
        }
        | {"relative_lifts": values.get("relative_lifts", {})}
        for question_type, values in metrics.get("holdout_by_question_type", {}).items()
    }
    report = f"""# MultiHop-RAG 检索实验报告

## 结论

- 运行编号：`{run_id}`
- 样本量：{len(cases)} 个 query
- Corpus：MultiHop-RAG 官方 corpus，609 篇文档
- 主指标：`Recall@10`
- 简历目标：GraphRAG/rerank 相比 vector-only Recall@10 相对提升 20%
- 当前结论：{status}
- 全量 adaptive_graph_rerank vs vector-only Recall@10 相对提升：{"N/A" if lift is None else f"{lift:.2%}"}
- Comparison holdout 子集结论：{comparison_status}
- Comparison holdout adaptive_graph_rerank vs vector-only Recall@10 相对提升：{"N/A" if comparison_holdout_lift is None else f"{comparison_holdout_lift:.2%}"}

## 实验方法

本实验使用 MultiHop-RAG 官方数据集评估多跳检索。索引阶段只使用 corpus 正文与元数据；query 的 `evidence_list` 只用于计算指标，不参与向量索引或图关系构建。

### 数据集

- 数据来源：MultiHop-RAG `MultiHopRAG.json` 与 `corpus.json`
- Query 抽样：跳过 `null_query`，固定随机种子 `{config["seed"]}` 抽取 {len(cases)} 条
- Gold：每条 query 的 evidence title 集合
- 问题类型分布：

```json
{json.dumps(dict(question_types), ensure_ascii=False, indent=2)}
```

### Baseline

- `vector_only`：Ollama `qwen3-embedding:4b` 生成 2560 维向量，Milvus 以 COSINE 检索文档。
- `bm25_only`：本地 BM25 关键词召回，作为传统稀疏检索基线。
- `graph_only`：BM25 种子召回 + Neo4j 文档实体/元数据关系扩展。
- `hybrid_rrf`：将 Milvus 向量排名和 Neo4j 图扩展排名用 RRF 融合。
- `metadata_graph_rerank`：在 Milvus top-50 与 BM25 top-50 候选上，用向量分、BM25 分、source、实体、标题/正文 token overlap 做无监督重排。
- `adaptive_graph_rerank`：对 comparison-like query 使用更重的 BM25/source 权重，其余 query 使用通用 metadata rerank 权重；query 类型由文本规则识别，不使用 gold evidence。

### Dev/Holdout 设定

- `dev_first_200`：用于快速失败分析和权重选择。
- `holdout_after_200`：未参与权重选择，用于检验泛化。
- 报告同时给出全量、holdout 和官方 `question_type` 分类型指标，避免只看最有利切片。

### 指标

- `Recall@5/10`：top-k 中命中的 evidence title 数量 / gold evidence title 数量。
- `Hit@10`：top-10 中是否至少命中一个 evidence title。
- `MRR@10`：第一个命中 evidence title 的 reciprocal rank。
- `nDCG@10`：按 evidence title 命中计算的归一化折损累计增益。

## 结果

| Mode | Recall@5 | Recall@10 | Hit@10 | MRR@10 | nDCG@10 | Avg Latency(s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

## 提升率

```text
adaptive_graph_rerank_vs_vector_recall_at_10 = (adaptive_graph_rerank_recall_at_10 - vector_only_recall_at_10) / vector_only_recall_at_10
```

当前全量结果：{"N/A" if lift is None else f"{lift:.2%}"}

## 分类型结果

全量 question_type Recall@10：

```json
{json.dumps(by_type_payload, ensure_ascii=False, indent=2)}
```

Holdout question_type Recall@10：

```json
{json.dumps(holdout_payload, ensure_ascii=False, indent=2)}
```

## 复现命令

```bash
conda run -n rag python evals/rag/run_multihop_retrieval_eval.py --query-limit {config["query_limit"]} --top-k {config["top_k"]}
```

## 输出文件

- 配置：`evals/results/rag/{run_id}/config.json`
- 原始检索结果：`evals/results/rag/{run_id}/raw_retrieval.jsonl`
- 指标：`evals/results/rag/{run_id}/metrics.json`
- 本报告：`evals/reports/multihop_rag_retrieval_evaluation.md`

## 注意事项

- 该实验为了避免答案泄漏，Neo4j 图只由 corpus 文本中的实体、source、category 构成，未使用 gold evidence 构边。
- 当前最有效的提升来自 metadata-aware rerank，而不是原始 RRF；这说明多跳任务的主要瓶颈是 top-50 候选排序和证据覆盖。
- 如果要把“多跳召回提升 20%”写进简历，必须以 holdout 或更大样本上的结果为准；本报告不会把 dev 局部结果包装成最终结论。
"""
    report_path.write_text(report, encoding="utf-8")


async def main_async(args: argparse.Namespace) -> int:
    ensure_dirs()
    run_id = args.run_id or datetime.now(timezone.utc).strftime("rag_multihop_%Y%m%dT%H%M%SZ")
    run_dir = PROJECT_ROOT / "evals" / "results" / "rag" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    raw_qa, raw_corpus = load_multihop_data()
    docs = build_corpus(raw_corpus)
    doc_by_id = {doc.doc_id: doc for doc in docs}
    title_to_doc = {doc.title: doc for doc in docs}
    source_index = build_source_index(docs)
    cases = build_query_cases(raw_qa, set(title_to_doc), args.query_limit, args.seed)
    bm25_index = build_bm25_index(docs)

    config = {
        "run_id": run_id,
        "seed": args.seed,
        "query_limit": args.query_limit,
        "corpus_count": len(docs),
        "top_k": args.top_k,
        "collection_name": args.collection,
        "dataset_id": args.dataset_id,
        "embedding_model": settings.ollama.embedding_model,
        "embedding_dim": EMBED_DIM,
        "modes": [
            "vector_only",
            "bm25_only",
            "graph_only",
            "hybrid_rrf",
            "metadata_graph_rerank",
            "adaptive_graph_rerank",
        ],
        "tuning_size": TUNING_SIZE,
    }
    write_json(run_dir / "config.json", config)

    print("Preparing Milvus index...", flush=True)
    milvus = prepare_milvus(docs, args.collection, args.rebuild_index, args.embed_batch_size)
    print("Preparing Neo4j graph...", flush=True)
    prepare_neo4j(docs, args.dataset_id, args.rebuild_graph)
    print("Loading Neo4j adjacency...", flush=True)
    graph_adjacency = load_neo4j_adjacency(args.dataset_id)

    query_embedding_path = PROJECT_ROOT / "evals" / "data" / "rag" / (
        f"query_embeddings_{settings.ollama.embedding_model.replace(':', '_')}_{EMBED_DIM}_{args.query_limit}_{args.seed}.json"
    )
    query_embeddings = embed_texts([case.query for case in cases], query_embedding_path, args.embed_batch_size)

    raw_rows: list[dict[str, Any]] = []
    for index, (case, query_embedding) in enumerate(zip(cases, query_embeddings), start=1):
        gold_titles = set(case.gold_titles)

        start = time.perf_counter()
        vector_ranking = search_milvus(milvus, args.collection, query_embedding, args.top_k)
        vector_latency = time.perf_counter() - start

        start = time.perf_counter()
        bm25_ranking = bm25_rank(case.query, docs, bm25_index, top_k=args.top_k)
        seed_scores = bm25_ranking[:12]
        graph_ranking = graph_expand(seed_scores, doc_by_id, graph_adjacency, args.top_k)
        graph_latency = time.perf_counter() - start

        start = time.perf_counter()
        hybrid_ranking = vector_preserving_hybrid(vector_ranking, graph_ranking, args.top_k)
        hybrid_latency = time.perf_counter() - start + vector_latency + graph_latency

        start = time.perf_counter()
        metadata_ranking = metadata_graph_rerank(
            case.query,
            vector_ranking,
            bm25_ranking,
            doc_by_id,
            source_index,
            args.top_k,
            adaptive=False,
        )
        metadata_latency = time.perf_counter() - start + vector_latency + graph_latency

        start = time.perf_counter()
        adaptive_ranking = metadata_graph_rerank(
            case.query,
            vector_ranking,
            bm25_ranking,
            doc_by_id,
            source_index,
            args.top_k,
            adaptive=True,
        )
        adaptive_latency = time.perf_counter() - start + vector_latency + graph_latency

        rankings = {
            "vector_only": vector_ranking,
            "bm25_only": bm25_ranking,
            "graph_only": graph_ranking,
            "hybrid_rrf": hybrid_ranking,
            "metadata_graph_rerank": metadata_ranking,
            "adaptive_graph_rerank": adaptive_ranking,
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
                "latency_seconds": {
                    "vector_only": vector_latency,
                    "bm25_only": graph_latency,
                    "graph_only": graph_latency,
                    "hybrid_rrf": hybrid_latency,
                    "metadata_graph_rerank": metadata_latency,
                    "adaptive_graph_rerank": adaptive_latency,
                }[mode],
            }
            row_rankings[mode] = [
                {"rank": rank, "doc_id": doc_id, "title": doc_by_id[doc_id].title, "score": score}
                for rank, (doc_id, score) in enumerate(ranking[:10], start=1)
            ]

        raw_rows.append(
            {
                "case": asdict(case),
                "query_analysis": {
                    "comparison_like": is_comparison_like_query(case.query),
                    "mentioned_source_count": mentioned_source_count(case.query, source_index),
                    "dates": sorted(query_dates(case.query)),
                },
                "metrics": row_metrics,
                "rankings": row_rankings,
            }
        )
        if index % 25 == 0 or index == len(cases):
            print(f"retrieved {index}/{len(cases)}", flush=True)

    metrics = aggregate_metrics(raw_rows, config["modes"])
    write_json(run_dir / "metrics.json", metrics)
    write_jsonl(run_dir / "raw_retrieval.jsonl", raw_rows)

    latest_dir = PROJECT_ROOT / "evals" / "results" / "rag" / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)
    write_json(latest_dir / "config.json", config)
    write_json(latest_dir / "metrics.json", metrics)
    write_jsonl(latest_dir / "raw_retrieval.jsonl", raw_rows)

    generate_report(run_id, cases, metrics, config)
    print(f"Report written to {PROJECT_ROOT / 'evals' / 'reports' / 'multihop_rag_retrieval_evaluation.md'}", flush=True)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate MultiHop-RAG retrieval with Milvus, Neo4j, and hybrid RRF.")
    parser.add_argument("--query-limit", type=int, default=200)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--dataset-id", default=DEFAULT_DATASET_ID)
    parser.add_argument("--embed-batch-size", type=int, default=16)
    parser.add_argument("--rebuild-index", action="store_true")
    parser.add_argument("--rebuild-graph", action="store_true")
    parser.add_argument("--run-id", default="")
    return parser.parse_args()


def main() -> int:
    return asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
