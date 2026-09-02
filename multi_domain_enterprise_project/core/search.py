from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from redis.asyncio import Redis

_HEADER_PATTERN = re.compile(
    r"^--- \[来源: (?P<source>.*?) \| (?P<metadata>.*?)\] ---$",
    re.MULTILINE,
)


def parse_retrieval_context(context: str) -> list[dict[str, Any]]:
    """把 RAG 的稳定引用格式转换为 API 可直接消费的证据列表。"""
    matches = list(_HEADER_PATTERN.finditer(context))
    evidence = []
    for index, match in enumerate(matches):
        content_start = match.end()
        content_end = matches[index + 1].start() if index + 1 < len(matches) else len(context)
        content = context[content_start:content_end].strip()
        metadata = {}
        for item in match.group("metadata").split(" | "):
            key, separator, value = item.partition(":")
            if separator:
                metadata[key.strip()] = value.strip()
        score_text = metadata.get("匹配分值", "")
        try:
            score = float(score_text)
        except ValueError:
            score = None
        version = _optional_int(metadata.get("版本"))
        chunk_index = _optional_int(metadata.get("切片"))
        identity = f"{match.group('source')}\n{content}".encode()
        evidence.append(
            {
                "id": hashlib.sha256(identity).hexdigest()[:16],
                "source": match.group("source").strip(),
                "content": content,
                "score": score,
                "kind": metadata.get("类型", "检索片段"),
                "backend": metadata.get("后端", ""),
                "document_id": metadata.get("文档ID") or None,
                "version": version,
                "chunk_index": chunk_index,
            }
        )
    return evidence


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _evidence_cache_key(tenant_id: str, user_id: str, evidence_id: str) -> str:
    scope = hashlib.sha256(f"{tenant_id}\0{user_id}".encode()).hexdigest()[:24]
    return f"rag:evidence:{scope}:{evidence_id}"


async def cache_search_evidence(
    redis: Redis,
    *,
    tenant_id: str,
    user_id: str,
    items: list[dict[str, Any]],
    ttl_seconds: int,
) -> None:
    if not items:
        return
    pipeline = redis.pipeline(transaction=True)
    for item in items:
        pipeline.set(
            _evidence_cache_key(tenant_id, user_id, str(item["id"])),
            json.dumps(item, ensure_ascii=False),
            ex=ttl_seconds,
        )
    await pipeline.execute()


async def get_cached_search_evidence(
    redis: Redis,
    *,
    tenant_id: str,
    user_id: str,
    evidence_id: str,
) -> dict[str, Any] | None:
    value = await redis.get(_evidence_cache_key(tenant_id, user_id, evidence_id))
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    payload = json.loads(value)
    return payload if isinstance(payload, dict) else None
