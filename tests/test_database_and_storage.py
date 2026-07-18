from __future__ import annotations

from pathlib import Path

import pytest

from config import settings
from multi_domain_enterprise_project.core.database import (
    SessionFactory,
    close_database,
    create_document,
    get_document,
    init_database,
    list_documents,
    reconfigure_database,
)
from multi_domain_enterprise_project.core.storage import KB_ROOT, parsed_document_path, remove_storage_path


@pytest.fixture
async def isolated_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings.runtime, "environment", "test")
    await reconfigure_database(f"sqlite+aiosqlite:///{tmp_path / 'metadata.db'}")
    await init_database()
    yield
    await close_database()


def document_payload(document_id: str, tenant_id: str, file_path: Path) -> dict:
    return {
        "id": document_id,
        "file_name": file_path.name,
        "title": "企业制度",
        "tenant_id": tenant_id,
        "owner_id": "owner-1",
        "acl": ["finance"],
        "file_path": str(file_path),
        "checksum": "a" * 64,
    }


@pytest.mark.asyncio
async def test_document_queries_are_tenant_scoped(isolated_database: None, tmp_path: Path) -> None:
    async with SessionFactory() as session:
        await create_document(session, document_payload("a" * 32, "tenant-a", tmp_path / "a.pdf"))
        await create_document(session, document_payload("b" * 32, "tenant-b", tmp_path / "b.pdf"))

        assert await get_document(session, "a" * 32, "tenant-b") is None
        tenant_a = await list_documents(session, "tenant-a")
        tenant_b = await list_documents(session, "tenant-b")

    assert [item["id"] for item in tenant_a] == ["a" * 32]
    assert [item["id"] for item in tenant_b] == ["b" * 32]


def test_parsed_paths_do_not_expose_tenant_id_and_delete_stays_in_storage() -> None:
    path = parsed_document_path("../sensitive-tenant", "c" * 32)
    assert path.is_relative_to(KB_ROOT)
    assert "sensitive-tenant" not in path.name
    path.write_text("parsed", encoding="utf-8")
    remove_storage_path(str(path))
    assert not path.exists()


def test_remove_storage_path_rejects_external_file(tmp_path: Path) -> None:
    external = tmp_path / "external.txt"
    external.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="知识库目录之外"):
        remove_storage_path(str(external))
    assert external.exists()

