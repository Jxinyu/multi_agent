"""RAG 召回率评估脚本。

目标
- 构建离线评估集：文档、入库、query 集。
- 评估 RAG 在不同检索模式下的召回表现。
- 支持按 query 的 gold 证据块/证据文档计算 Recall@K、MRR、Hit Rate。

使用方式
1. 准备样本文档目录（默认 `tests/eval_rag_recall/sample_docs`）。
2. 运行 `build_dataset_from_documents()` 生成 query 数据集。
3. 运行 `run_recall_benchmark()` 执行入库与召回评估。

说明
- 这是评估脚本，不是单元测试。
- 如果尚未准备真实文档，也可以先直接编辑 `rag_recall_cases.json` 填入 query/证据集。
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

from multi_domain_enterprise_project.rag.rag_service import insert_service, retrieve_service

TESTS_DIR = Path(__file__).resolve().parent
DATASET_PATH = TESTS_DIR / "rag_recall_cases.json"
REPORT_PATH = TESTS_DIR / "rag_recall_scores.json"
SAMPLE_DOC_DIR = TESTS_DIR / "sample_docs"
DEFAULT_TENANT_ID = "rag_recall_eval"
DEFAULT_USER_ID = "rag_recall_eval"
DEFAULT_ACL = "public"
DEFAULT_TITLE_PREFIX = "rag_recall"


@dataclass(frozen=True)
class DocumentSpec:
    """用于实验的数据文档定义。"""

    file_name: str
    title: str
    tenant_id: str = DEFAULT_TENANT_ID
    user_id: str = DEFAULT_USER_ID
    acl: str = DEFAULT_ACL
    mode: str = "mg"


@dataclass(frozen=True)
class RecallCase:
    """单条召回评估样本。"""

    case_id: str
    query: str
    relevant_docs: list[str] = field(default_factory=list)
    relevant_chunks: list[str] = field(default_factory=list)
    mode: str = "milvus"
    k_values: list[int] = field(default_factory=lambda: [1, 3, 5])
    domain: str = "general"
    difficulty: str = "medium"
    notes: str = ""


@dataclass
class RetrievalHit:
    rank: int
    source_file: str
    score: float | None
    snippet: str


@dataclass
class RecallCaseResult:
    case_id: str
    query: str
    mode: str
    relevant_docs: list[str]
    hits: list[RetrievalHit]
    recall_at_k: dict[str, float]
    hit_at_k: dict[str, bool]
    mrr: float
    passed: bool
    reason: str


MARKER_RE = re.compile(r"\[来源:\s*(?P<file>[^|\]]+)\s*\|.*?匹配分值:\s*(?P<score>[-+]?\d*\.?\d+)\]")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_filename(name: str) -> str:
    return Path(name).name.strip()


def _extract_hits(answer_text: str) -> list[RetrievalHit]:
    hits: list[RetrievalHit] = []
    if not answer_text:
        return hits

    chunks = re.split(r"\n\s*--- \[来源:", answer_text)
    if chunks and chunks[0].startswith("###"):
        chunks[0] = ""

    for idx, chunk in enumerate(chunks):
        if not chunk.strip():
            continue
        text = chunk if chunk.startswith("--- [来源:") else f"--- [来源:{chunk}"
        m = MARKER_RE.search(text)
        if not m:
            continue
        source_file = _normalize_filename(m.group("file"))
        score = float(m.group("score"))
        snippet = text.split("--- [来源:", 1)[-1].strip()
        hits.append(RetrievalHit(rank=len(hits) + 1, source_file=source_file, score=score, snippet=snippet))
    return hits


def _compute_metrics(hits: list[RetrievalHit], relevant_docs: set[str], k_values: list[int]) -> tuple[dict[str, float], dict[str, bool], float]:
    recall_at_k: dict[str, float] = {}
    hit_at_k: dict[str, bool] = {}
    mrr = 0.0

    for k in k_values:
        top_k = hits[:k]
        retrieved_docs = {_normalize_filename(hit.source_file) for hit in top_k}
        hit_count = len(retrieved_docs & relevant_docs)
        recall = hit_count / len(relevant_docs) if relevant_docs else 0.0
        recall_at_k[str(k)] = recall
        hit_at_k[str(k)] = hit_count > 0

    for idx, hit in enumerate(hits, start=1):
        if _normalize_filename(hit.source_file) in relevant_docs:
            mrr = 1.0 / idx
            break

    return recall_at_k, hit_at_k, mrr


async def ingest_documents(documents: Iterable[DocumentSpec], doc_root: Path | None = None, mode: str = "mg") -> list[dict[str, Any]]:
    """将测试文档入库，形成可重复召回实验环境。"""
    doc_root = doc_root or SAMPLE_DOC_DIR
    results: list[dict[str, Any]] = []

    for doc in documents:
        file_path = doc_root / doc.file_name
        if not file_path.exists():
            raise FileNotFoundError(f"测试文档不存在: {file_path}")

        await insert_service(
            file_path=str(file_path),
            tenant_id=doc.tenant_id,
            user_id=doc.user_id,
            title=doc.title,
            acl=doc.acl,
            mode=mode or doc.mode,
        )
        results.append({"file_name": doc.file_name, "title": doc.title, "tenant_id": doc.tenant_id})

    return results


def build_dataset_from_documents(documents: list[dict[str, Any]], output_path: Path = DATASET_PATH) -> list[RecallCase]:
    """根据文档清单生成一版初始 query 集。

    该函数不会自动理解文档语义，只是给出可编辑的数据骨架，方便人工补充 gold 证据。
    """
    cases: list[RecallCase] = []
    for idx, doc in enumerate(documents, start=1):
        file_name = _normalize_filename(doc["file_name"])
        title = doc.get("title", file_name)
        cases.append(
            RecallCase(
                case_id=f"{idx:03d}",
                query=f"请检索与《{title}》相关的核心内容，并返回最相关依据。",
                relevant_docs=[file_name],
                relevant_chunks=[],
                mode="milvus",
                domain=doc.get("domain", "general"),
                difficulty="easy",
                notes="自动生成的初始 query，建议人工改写为更贴近真实业务的检索问题。",
            )
        )

    _write_json(output_path, [asdict(item) for item in cases])
    return cases


def load_cases(path: Path = DATASET_PATH) -> list[RecallCase]:
    raw = _read_json(path, default=[])
    return [RecallCase(**item) for item in raw]


async def run_recall_benchmark(query_cases: list[RecallCase] | None = None, mode_override: str | None = None) -> dict[str, Any]:
    """执行召回率评估。"""
    cases = query_cases or load_cases()
    results: list[RecallCaseResult] = []

    for case in cases:
        mode = mode_override or case.mode
        answer = await retrieve_service(
            query_str=case.query,
            title=None,
            tenant_id=None,
            acl_list=None,
            mode=mode,
        )
        hits = _extract_hits(answer)
        relevant_docs = { _normalize_filename(item) for item in case.relevant_docs }
        recall_at_k, hit_at_k, mrr = _compute_metrics(hits, relevant_docs, case.k_values)
        passed = any(hit_at_k.values())
        reason = "命中相关文档" if passed else "未命中任何相关文档"

        results.append(
            RecallCaseResult(
                case_id=case.case_id,
                query=case.query,
                mode=mode,
                relevant_docs=case.relevant_docs,
                hits=hits,
                recall_at_k=recall_at_k,
                hit_at_k=hit_at_k,
                mrr=mrr,
                passed=passed,
                reason=reason,
            )
        )
        print(f"[{case.case_id}] mode={mode} recall@k={recall_at_k} mrr={mrr:.3f} passed={passed}")

    total = len(results)
    avg_recall = {
        k: (sum(item.recall_at_k[k] for item in results) / total) if total else 0.0
        for k in (str(v) for v in (1, 3, 5))
    }
    avg_mrr = (sum(item.mrr for item in results) / total) if total else 0.0
    pass_rate = (sum(1 for item in results if item.passed) / total) if total else 0.0

    report = {
        "total_cases": total,
        "pass_rate": pass_rate,
        "avg_recall_at_k": avg_recall,
        "avg_mrr": avg_mrr,
        "failed_cases": [asdict(item) for item in results if not item.passed],
        "results": [
            {
                **asdict(item),
                "hits": [asdict(hit) for hit in item.hits],
            }
            for item in results
        ],
        "evaluation_notes": {
            "goal": "衡量检索系统对 gold 证据文档/证据块的召回能力",
            "metrics": ["Recall@K", "Hit@K", "MRR"],
            "suggested_next_step": "为每个 query 显式补充 relevant_chunks，用于更细粒度的 chunk-level 召回评估",
        },
    }
    _write_json(REPORT_PATH, report)
    return report


async def main() -> None:
    if not DATASET_PATH.exists():
        print(f"未找到数据集文件: {DATASET_PATH}")
        print("请先准备 `rag_recall_cases.json`，或使用 build_dataset_from_documents() 生成初始版本。")
        return

    report = await run_recall_benchmark()
    print(f"\nSaved score report to: {REPORT_PATH}")
    print(f"Pass rate: {report['pass_rate']:.2%}")
    print(f"Avg MRR: {report['avg_mrr']:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
