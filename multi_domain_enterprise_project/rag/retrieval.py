from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


def _node(item: Any) -> Any:
    return getattr(item, "node", item)


def _score(item: Any) -> float:
    value = getattr(item, "score", None)
    return float(value) if value is not None else float("-inf")


def retrieval_identity(item: Any) -> str:
    node = _node(item)
    metadata = getattr(node, "metadata", {}) or {}
    identity_parts = (
        metadata.get("tenant_id"),
        metadata.get("document_id"),
        metadata.get("version"),
        metadata.get("chunk_index"),
    )
    if all(part is not None for part in identity_parts):
        return "chunk:" + ":".join(str(part) for part in identity_parts)
    node_id = getattr(node, "node_id", None) or getattr(node, "id_", None)
    if node_id:
        return f"node:{node_id}"
    content = node.get_content() if hasattr(node, "get_content") else str(node)
    return "content:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def deduplicate_node_results(nodes: Sequence[Any]) -> list[Any]:
    selected: dict[str, Any] = {}
    for item in nodes:
        key = retrieval_identity(item)
        if key not in selected or _score(item) > _score(selected[key]):
            selected[key] = item
    return sorted(selected.values(), key=_score, reverse=True)


@dataclass(frozen=True)
class FusedRetrievalResult:
    node_with_score: Any
    backends: tuple[str, ...]
    fusion_score: float

    @property
    def node(self) -> Any:
        return _node(self.node_with_score)

    @property
    def score(self) -> float | None:
        return getattr(self.node_with_score, "score", None)


def fuse_backend_results(
    backend_results: Mapping[str, Sequence[Any]],
    *,
    rrf_k: int = 60,
    limit: int | None = None,
) -> list[FusedRetrievalResult]:
    if rrf_k < 1:
        raise ValueError("RRF 平滑常数必须大于 0")
    if limit is not None and limit < 1:
        raise ValueError("融合候选上限必须大于 0")
    fused: dict[str, FusedRetrievalResult] = {}
    for backend, results in backend_results.items():
        ranked_results = deduplicate_node_results(results)
        for rank, item in enumerate(ranked_results, start=1):
            key = retrieval_identity(item)
            contribution = 1.0 / (rrf_k + rank)
            current = fused.get(key)
            if current is None:
                fused[key] = FusedRetrievalResult(item, (backend,), contribution)
                continue
            backends = tuple(dict.fromkeys((*current.backends, backend)))
            fused[key] = FusedRetrievalResult(
                current.node_with_score,
                backends,
                current.fusion_score + contribution,
            )
    ordered = sorted(
        fused.values(),
        key=lambda item: (item.fusion_score, len(item.backends), retrieval_identity(item.node_with_score)),
        reverse=True,
    )
    return ordered[:limit] if limit is not None else ordered


def attach_reranked_provenance(
    reranked_nodes: Sequence[Any],
    fused_candidates: Sequence[FusedRetrievalResult],
) -> list[FusedRetrievalResult]:
    provenance = {
        retrieval_identity(item.node_with_score): (item.backends, item.fusion_score)
        for item in fused_candidates
    }
    results = []
    for node in reranked_nodes:
        key = retrieval_identity(node)
        if key not in provenance:
            raise ValueError("重排结果包含融合候选之外的节点")
        backends, fusion_score = provenance[key]
        results.append(FusedRetrievalResult(node, backends, fusion_score))
    return results


def format_fused_context(
    results: Sequence[FusedRetrievalResult],
    *,
    max_chars: int,
    max_chunks_per_document: int,
) -> str:
    if not results:
        return "检索的结果为空"
    if max_chars < 1 or max_chunks_per_document < 1:
        raise ValueError("上下文长度和单文档切片数必须大于 0")
    parts = ["### 融合检索参考资料："]
    document_counts: dict[str, int] = {}
    for result in results:
        node = result.node
        metadata = getattr(node, "metadata", {}) or {}
        document_key = str(metadata.get("document_id") or metadata.get("file_name") or retrieval_identity(node))
        if document_counts.get(document_key, 0) >= max_chunks_per_document:
            continue
        file_name = metadata.get("file_name", "未知文件")
        backend_names = ", ".join(result.backends)
        score = result.score
        score_text = f"{score:.4f}" if score is not None else "N/A"
        content = node.get_content().strip() if hasattr(node, "get_content") else str(node).strip()
        header = (
            f"--- [来源: {file_name} | 后端: {backend_names} | 匹配分值: {score_text}] ---"
        )
        section = f"{header}\n{content}"
        candidate = "\n\n".join((*parts, section))
        if len(candidate) > max_chars:
            continue
        parts.append(section)
        document_counts[document_key] = document_counts.get(document_key, 0) + 1
    return "\n\n".join(parts) if len(parts) > 1 else "检索的结果为空"
