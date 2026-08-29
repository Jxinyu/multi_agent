from __future__ import annotations

import hashlib
import re
from typing import Any

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
        identity = f"{match.group('source')}\n{content}".encode()
        evidence.append(
            {
                "id": hashlib.sha256(identity).hexdigest()[:16],
                "source": match.group("source").strip(),
                "content": content,
                "score": score,
                "kind": metadata.get("类型", "检索片段"),
                "backend": metadata.get("后端", ""),
            }
        )
    return evidence
