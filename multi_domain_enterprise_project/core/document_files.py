from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from multi_domain_enterprise_project.core.storage import FILES_ROOT

PreviewKind = Literal["pdf", "image", "text", "unsupported"]

_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".bmp": "image/bmp",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def preview_kind(file_name: str) -> PreviewKind:
    extension = Path(file_name).suffix.lower()
    if extension == ".pdf":
        return "pdf"
    if extension in {".png", ".jpg", ".jpeg", ".bmp"}:
        return "image"
    if extension in {".txt", ".md", ".csv", ".json"}:
        return "text"
    return "unsupported"


def resolve_document_file(item: dict[str, Any]) -> tuple[Path, str, str, PreviewKind]:
    file_name = Path(str(item.get("file_name") or "")).name
    path_value = item.get("file_path")
    if not file_name or not path_value:
        raise FileNotFoundError("文档原文件信息不完整")

    path = Path(str(path_value)).resolve()
    if not path.is_relative_to(FILES_ROOT.resolve()) or not path.is_file():
        raise FileNotFoundError("文档原文件不存在")
    extension = Path(file_name).suffix.lower()
    if extension != path.suffix.lower() or extension not in _MEDIA_TYPES:
        raise FileNotFoundError("文档原文件类型无效")
    return path, file_name, _MEDIA_TYPES[extension], preview_kind(file_name)
