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

    @property
    def node(self) -> Any:
        return _node(self.node_with_score)

    @property
    def score(self) -> float | None:
        return getattr(self.node_with_score, "score", None)


def fuse_backend_results(
    backend_results: Mapping[str, Sequence[Any]],
) -> list[FusedRetrievalResult]:
    fused: dict[str, FusedRetrievalResult] = {}
    for backend, results in backend_results.items():
        for item in results:
            key = retrieval_identity(item)
            current = fused.get(key)
            if current is None:
                fused[key] = FusedRetrievalResult(item, (backend,))
                continue
            backends = tuple(dict.fromkeys((*current.backends, backend)))
            winner = item if _score(item) > _score(current.node_with_score) else current.node_with_score
            fused[key] = FusedRetrievalResult(winner, backends)
    return sorted(fused.values(), key=lambda item: _score(item.node_with_score), reverse=True)


def format_fused_context(results: Sequence[FusedRetrievalResult]) -> str:
    if not results:
        return "检索的结果为空"
    parts = ["### 融合检索参考资料："]
    for result in results:
        node = result.node
        metadata = getattr(node, "metadata", {}) or {}
        file_name = metadata.get("file_name", "未知文件")
        backend_names = ", ".join(result.backends)
        score = result.score
        score_text = f"{score:.4f}" if score is not None else "N/A"
        content = node.get_content().strip() if hasattr(node, "get_content") else str(node).strip()
        header = (
            f"--- [来源: {file_name} | 后端: {backend_names} | 匹配分值: {score_text}] ---"
        )
        parts.append(f"{header}\n{content}")
    return "\n\n".join(parts)
