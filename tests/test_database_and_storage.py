from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from config import settings
from multi_domain_enterprise_project.core.audit import append_audit_event, list_audit_events
from multi_domain_enterprise_project.core.auth import CurrentUser, require_permissions
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


@pytest.mark.asyncio
async def test_audit_queries_are_tenant_scoped_and_cursor_paginated(isolated_database: None) -> None:
    async with SessionFactory() as session:
        for index in range(3):
            await append_audit_event(
                session,
                tenant_id="tenant-a",
                actor_id="user-a",
                source="api",
                action="document.read",
                resource_type="document",
                resource_id=f"document-{index}",
                outcome="success",
                request_id=f"request-{index}",
                metadata={"result_count": index},
            )
        await append_audit_event(
            session,
            tenant_id="tenant-b",
            actor_id="user-b",
            source="api",
            action="document.read",
            resource_type="document",
            outcome="success",
        )

        first_page, cursor = await list_audit_events(session, tenant_id="tenant-a", limit=2)
        second_page, next_cursor = await list_audit_events(
            session,
            tenant_id="tenant-a",
            limit=2,
            cursor=cursor,
            actor_id="user-a",
            outcome="success",
        )

    assert len(first_page) == 2
    assert cursor is not None
    assert len(second_page) == 1
    assert next_cursor is None
    assert {event["tenant_id"] for event in first_page + second_page} == {"tenant-a"}
    assert not {event["id"] for event in first_page}.intersection(event["id"] for event in second_page)


@pytest.mark.asyncio
async def test_audit_rejects_sensitive_metadata_and_invalid_cursor(isolated_database: None) -> None:
    async with SessionFactory() as session:
        with pytest.raises(ValueError, match="敏感字段"):
            await append_audit_event(
                session,
                tenant_id="tenant-a",
                actor_id="user-a",
                source="api",
                action="chat.requested",
                resource_type="conversation",
                outcome="success",
                metadata={"nested": {"file_name": "sensitive.pdf"}},
            )
        with pytest.raises(ValueError, match="游标无效"):
            await list_audit_events(session, tenant_id="tenant-a", limit=10, cursor="not-base64")


@pytest.mark.asyncio
async def test_permission_denial_is_audited(isolated_database: None) -> None:
    user = CurrentUser(
        user_id="user-a",
        username="tester",
        tenant_id="tenant-a",
        role="reader",
        permissions=["kb:read"],
        access_token="not-persisted",
    )
    dependency = require_permissions("audit:read")
    with pytest.raises(HTTPException) as exc_info:
        await dependency(user)
    assert getattr(exc_info.value, "status_code", None) == 403

    async with SessionFactory() as session:
        events, _ = await list_audit_events(session, tenant_id="tenant-a", limit=10)
    assert events[0]["action"] == "authorization.denied"
    assert events[0]["outcome"] == "denied"
    assert events[0]["metadata"]["missing_permissions"] == ["audit:read"]


@pytest.mark.asyncio
async def test_database_startup_rejects_outdated_columns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_path = tmp_path / "outdated.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE ingestion_jobs (id VARCHAR(64) PRIMARY KEY)")

    monkeypatch.setattr(settings.runtime, "environment", "test")
    await reconfigure_database(f"sqlite+aiosqlite:///{database_path}")
    with pytest.raises(RuntimeError, match="ingestion_jobs.*requested_by"):
        await init_database()
    await close_database()


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
