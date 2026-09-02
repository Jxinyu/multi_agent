from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from multi_domain_enterprise_project.core.storage import PARSED_ROOT


async def read_document_preview(
    item: dict[str, Any],
    *,
    max_chars: int,
) -> tuple[str | None, bool]:
    path_value = item.get("file_path_md")
    if not path_value:
        return None, False
    path = Path(str(path_value)).resolve()
    if not path.is_relative_to(PARSED_ROOT.resolve()):
        raise RuntimeError("解析文档路径不在受控目录内")
    if not path.is_file():
        return None, False

    content = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
    return content[:max_chars], len(content) > max_chars
