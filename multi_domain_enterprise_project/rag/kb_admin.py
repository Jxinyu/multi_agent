from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

KB_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "knowledge_base"
REGISTRY_PATH = KB_ROOT / "registry.json"


@dataclass
class KnowledgeDocument:
    id: str
    file_name: str
    title: str
    tenant_id: str
    owner_id: str
    acl: str
    upload_time: str
    mode: str
    file_path: str
    file_path_md: str | None = None
    status: str = "uploaded"
    chunk_count: int = 0
    error: str | None = None
    ingest_progress: int = 0
    ingest_total: int = 0
    ingest_message: str | None = None
    batch_id: str | None = None


def ensure_kb_root() -> None:
    KB_ROOT.mkdir(parents=True, exist_ok=True)
    (KB_ROOT / "files").mkdir(parents=True, exist_ok=True)
    (KB_ROOT / "markdown").mkdir(parents=True, exist_ok=True)


def load_registry() -> list[dict[str, Any]]:
    ensure_kb_root()
    if not REGISTRY_PATH.exists():
        return []
    try:
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_registry(items: list[dict[str, Any]]) -> None:
    ensure_kb_root()
    REGISTRY_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_document(item: KnowledgeDocument) -> KnowledgeDocument:
    registry = load_registry()
    payload = asdict(item)
    registry = [doc for doc in registry if doc.get("id") != item.id]
    registry.insert(0, payload)
    save_registry(registry)
    return item


def patch_document(doc_id: str, **updates: Any) -> dict[str, Any] | None:
    registry = load_registry()
    updated = None
    for doc in registry:
        if doc.get("id") == doc_id:
            doc.update({k: v for k, v in updates.items() if v is not None})
            updated = doc
            break
    if updated is not None:
        save_registry(registry)
    return updated


def patch_documents_by_ids(doc_ids: list[str], **updates: Any) -> list[dict[str, Any]]:
    registry = load_registry()
    updated_docs: list[dict[str, Any]] = []
    doc_id_set = set(doc_ids)
    for doc in registry:
        if doc.get("id") in doc_id_set:
            doc.update({k: v for k, v in updates.items() if v is not None})
            updated_docs.append(doc)
    if updated_docs:
        save_registry(registry)
    return updated_docs


def delete_document(doc_id: str) -> bool:
    registry = load_registry()
    doc = next((item for item in registry if item.get("id") == doc_id), None)
    if not doc:
        return False
    registry = [item for item in registry if item.get("id") != doc_id]
    save_registry(registry)
    for key in ("file_path", "file_path_md"):
        path = doc.get(key)
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass
    return True


def clear_knowledge_base() -> None:
    if KB_ROOT.exists():
        shutil.rmtree(KB_ROOT, ignore_errors=True)
    ensure_kb_root()
    save_registry([])


def create_document_id() -> str:
    return uuid.uuid4().hex
