from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from llama_index.core import QueryBundle
from llama_index.core.schema import NodeWithScore, TextNode

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402
from multi_domain_enterprise_project.rag.retrieval import fuse_backend_results  # noqa: E402
from multi_domain_enterprise_project.rag.runtime import get_reranker  # noqa: E402

QUERY = "企业员工跨城市出差时，住宿费、交通费和审批流程应遵守哪些规定？"
CONTENT_TEMPLATES = (
    "员工跨城市出差前应提交出差申请，经直属负责人审批后预订交通和住宿。",
    "住宿费按目的地等级执行限额，超出标准的部分需要部门负责人书面说明。",
    "交通费报销需要提供行程单、发票和支付凭证，财务复核后统一入账。",
    "差旅结束后十个工作日内提交报销，缺少必要凭证的申请将退回补充。",
    "采购合同应由法务审核，合同归档流程与员工差旅报销政策无直接关系。",
    "研发环境的服务变更需要完成代码审查、自动化测试和发布审批。",
)


def build_backend_candidates(per_backend: int, overlap: int) -> dict[str, list[NodeWithScore]]:
    if overlap < 0 or overlap > per_backend:
        raise ValueError("overlap 必须在 0 和 per_backend 之间")
    total = per_backend * 2 - overlap

    def result(index: int, rank: int, backend: str) -> NodeWithScore:
        text = f"条款 {index + 1}。{CONTENT_TEMPLATES[index % len(CONTENT_TEMPLATES)]}"
        return NodeWithScore(
            node=TextNode(
                id_=f"{backend}-{index}",
                text=text,
                metadata={
                    "tenant_id": "benchmark",
                    "document_id": f"document-{index}",
                    "version": 1,
                    "chunk_index": 0,
                    "file_name": f"policy-{index}.txt",
                },
            ),
            score=1.0 - rank / 1000,
        )

    milvus_ids = list(range(per_backend))
    neo4j_ids = list(range(overlap)) + list(range(per_backend, total))
    return {
        "milvus": [result(index, rank, "milvus") for rank, index in enumerate(milvus_ids, start=1)],
        "neo4j": [result(index, rank, "neo4j") for rank, index in enumerate(neo4j_ids, start=1)],
    }


def legacy_duration(reranker, per_backend: int, overlap: int) -> float:
    groups = build_backend_candidates(per_backend, overlap)
    query = QueryBundle(query_str=QUERY)
    started = time.perf_counter()
    for candidates in groups.values():
        reranker.postprocess_nodes(nodes=candidates, query_bundle=query)
    return time.perf_counter() - started


def optimized_duration(reranker, per_backend: int, overlap: int, fusion_limit: int) -> tuple[float, int]:
    groups = build_backend_candidates(per_backend, overlap)
    query = QueryBundle(query_str=QUERY)
    started = time.perf_counter()
    fused = fuse_backend_results(groups, rrf_k=settings.retrieval.rrf_k, limit=fusion_limit)
    reranker.postprocess_nodes(
        nodes=[candidate.node_with_score for candidate in fused],
        query_bundle=query,
    )
    return time.perf_counter() - started, len(fused)


def summarize(values: list[float]) -> dict[str, float]:
    return {
        "mean_seconds": round(statistics.mean(values), 4),
        "median_seconds": round(statistics.median(values), 4),
        "min_seconds": round(min(values), 4),
        "max_seconds": round(max(values), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="比较双后端分别重排与融合后单次重排的本机开销")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--per-backend", type=int, default=40)
    parser.add_argument("--overlap", type=int, default=20)
    parser.add_argument("--fusion-limit", type=int, default=40)
    args = parser.parse_args()
    if args.iterations < 1 or args.per_backend < 1 or args.fusion_limit < 1:
        raise ValueError("iterations、per-backend 和 fusion-limit 必须大于 0")

    reranker = get_reranker()
    warmup = build_backend_candidates(min(args.per_backend, 8), min(args.overlap, 4))["milvus"]
    reranker.postprocess_nodes(nodes=warmup, query_bundle=QueryBundle(query_str=QUERY))

    legacy_samples: list[float] = []
    optimized_samples: list[float] = []
    fused_count = 0
    for iteration in range(args.iterations):
        if iteration % 2 == 0:
            legacy_samples.append(legacy_duration(reranker, args.per_backend, args.overlap))
            optimized, fused_count = optimized_duration(
                reranker, args.per_backend, args.overlap, args.fusion_limit
            )
            optimized_samples.append(optimized)
        else:
            optimized, fused_count = optimized_duration(
                reranker, args.per_backend, args.overlap, args.fusion_limit
            )
            optimized_samples.append(optimized)
            legacy_samples.append(legacy_duration(reranker, args.per_backend, args.overlap))

    legacy_pairs = args.per_backend * 2
    optimized_pairs = fused_count
    legacy_median = statistics.median(legacy_samples)
    optimized_median = statistics.median(optimized_samples)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    payload = {
        "run_id": f"runtime_rerank_{timestamp}",
        "created_at": datetime.now(UTC).isoformat(),
        "environment": platform.platform(),
        "reranker_model": settings.reranker.model_path,
        "top_n": settings.reranker.top_n,
        "iterations": args.iterations,
        "candidate_setup": {
            "per_backend": args.per_backend,
            "overlap": args.overlap,
            "fusion_limit": args.fusion_limit,
        },
        "legacy_separate_rerank": {
            "reranker_calls": 2,
            "input_pairs": legacy_pairs,
            **summarize(legacy_samples),
        },
        "optimized_global_rerank": {
            "reranker_calls": 1,
            "input_pairs": optimized_pairs,
            **summarize(optimized_samples),
        },
        "relative_change": {
            "input_pairs": round(optimized_pairs / legacy_pairs - 1, 4),
            "median_latency": round(optimized_median / legacy_median - 1, 4),
        },
        "method": "模型加载和预热不计时；两方案使用同一查询与候选文本；交替执行以降低顺序偏差。",
        "scope": "该结果只衡量本机 BGE 重排开销，不代表线上端到端延迟或公开数据集准确率。",
    }
    result_dir = PROJECT_ROOT / "evals" / "results" / "rag" / payload["run_id"]
    result_dir.mkdir(parents=True, exist_ok=False)
    result_path = result_dir / "metrics.json"
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"结果已写入: {result_path}")


if __name__ == "__main__":
    main()
