from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from config import settings
from multi_domain_enterprise_project import main
from multi_domain_enterprise_project.api import jobs
from multi_domain_enterprise_project.core.audit import (
    append_audit_event,
    get_audit_event,
    list_audit_events,
    list_request_audit_events,
)
from multi_domain_enterprise_project.core.auth import CurrentUser, require_permissions
from multi_domain_enterprise_project.core.database import (
    ConversationFeedbackRecord,
    SessionFactory,
    append_conversation_message,
    close_database,
    create_document,
    create_job,
    ensure_conversation,
    finish_conversation_turn,
    get_document,
    get_user_conversation,
    init_database,
    list_documents,
    list_tenant_conversation_feedback,
    list_user_conversations,
    reconfigure_database,
    set_conversation_feedback,
    update_job,
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


def job_reader(tenant_id: str) -> CurrentUser:
    return CurrentUser(
        user_id=f"admin-{tenant_id}",
        username="admin",
        tenant_id=tenant_id,
        role="admin",
        permissions=["kb:read"],
        groups=[],
        access_token="token",
    )


def document_owner() -> CurrentUser:
    return CurrentUser(
        user_id="owner-1",
        username="owner",
        tenant_id="tenant-a",
        role="user",
        permissions=["kb:read"],
        groups=[],
        access_token="token",
    )


def knowledge_item(document_id: str = "a" * 32) -> dict:
    return {
        "id": document_id,
        "file_name": "a.pdf",
        "title": "企业制度",
        "tenant_id": "tenant-a",
        "owner_id": "owner-1",
        "acl": ["finance"],
        "upload_time": "2026-09-02T08:00:00+00:00",
        "mode": "graphrag",
        "status": "queued",
        "chunk_count": 0,
        "error": None,
        "ingest_progress": 0,
        "ingest_total": 1,
        "ingest_message": "等待入库 Worker",
        "batch_id": None,
        "version": 1,
        "checksum": "a" * 64,
        "backend_status": {},
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
async def test_job_list_and_detail_are_tenant_scoped_and_filterable(
    isolated_database: None,
    tmp_path: Path,
) -> None:
    async with SessionFactory() as session:
        await create_document(session, document_payload("a" * 32, "tenant-a", tmp_path / "a.pdf"))
        await create_document(session, document_payload("b" * 32, "tenant-b", tmp_path / "b.pdf"))
        first = await create_job(
            session,
            job_id="job-a-1",
            document_id="a" * 32,
            tenant_id="tenant-a",
            operation="ingest",
            mode="mg",
            requested_by="user-a",
            request_id="request-a-1",
        )
        await update_job(session, first.id, status="processing", attempts=1)
        await create_job(
            session,
            job_id="job-a-2",
            document_id="a" * 32,
            tenant_id="tenant-a",
            operation="ingest",
            mode="milvus",
            requested_by="user-a",
            request_id="request-a-2",
        )
        await create_job(
            session,
            job_id="job-b-1",
            document_id="b" * 32,
            tenant_id="tenant-b",
            operation="ingest",
            mode="graph",
            requested_by="user-b",
            request_id="request-b-1",
        )

        all_jobs = await jobs.list_jobs(job_reader("tenant-a"), session, limit=50, offset=0)
        processing = await jobs.list_jobs(
            job_reader("tenant-a"), session, job_status="processing", limit=50, offset=0
        )
        second_page = await jobs.list_jobs(job_reader("tenant-a"), session, limit=1, offset=1)
        detail = await jobs.get_job("job-a-1", job_reader("tenant-a"), session)
        user_jobs = await jobs.list_user_jobs(document_owner(), session, limit=50, offset=0)
        denied_jobs = await jobs.list_user_jobs(job_reader("tenant-a"), session, limit=50, offset=0)
        user_detail = await jobs.get_user_job("job-a-1", document_owner(), session)

        with pytest.raises(HTTPException) as exc_info:
            await jobs.get_job("job-b-1", job_reader("tenant-a"), session)
        with pytest.raises(HTTPException) as denied_detail:
            await jobs.get_user_job("job-a-1", job_reader("tenant-a"), session)

    assert all_jobs.total == 2
    assert {item.id for item in all_jobs.items} == {"job-a-1", "job-a-2"}
    assert processing.total == 1
    assert processing.items[0].id == "job-a-1"
    assert len(second_page.items) == 1
    assert detail.file_name == "a.pdf"
    assert detail.request_id == "request-a-1"
    assert user_jobs.total == 2
    assert user_detail.id == "job-a-1"
    assert denied_jobs.total == 0
    assert exc_info.value.status_code == 404
    assert denied_detail.value.status_code == 404


@pytest.mark.asyncio
async def test_ingest_submission_returns_persisted_job_id(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_require(session, document_id, current_user):
        return {**knowledge_item(document_id), "status": "ready"}

    async def fake_update(session, document_id, tenant_id, **updates):
        captured["update"] = {"document_id": document_id, "tenant_id": tenant_id, **updates}
        return knowledge_item(document_id)

    async def fake_queue(session, item, **kwargs):
        captured["queue"] = kwargs
        return "job-real-1"

    monkeypatch.setattr(main, "_require_document", fake_require)
    monkeypatch.setattr(main, "update_document", fake_update)
    monkeypatch.setattr(main, "_queue_document_job", fake_queue)

    response = await main.ingest_document(
        "a" * 32,
        main.IngestRequest(mode="graphrag"),
        job_reader("tenant-a"),
        object(),
    )

    assert response.job_ids == ["job-real-1"]
    assert response.items is not None
    assert response.items[0].id == "a" * 32
    assert captured["queue"]["operation"] == "ingest"
    assert captured["queue"]["mode"] == "graph"


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
async def test_audit_detail_and_request_trace_are_tenant_scoped(isolated_database: None) -> None:
    async with SessionFactory() as session:
        first = await append_audit_event(
            session,
            tenant_id="tenant-a",
            actor_id="user-a",
            source="api",
            action="chat.requested",
            resource_type="conversation",
            outcome="success",
            request_id="trace-shared",
        )
        second = await append_audit_event(
            session,
            tenant_id="tenant-a",
            actor_id="user-a",
            source="worker",
            action="chat.completed",
            resource_type="conversation",
            outcome="success",
            request_id="trace-shared",
        )
        await append_audit_event(
            session,
            tenant_id="tenant-b",
            actor_id="user-b",
            source="api",
            action="chat.failed",
            resource_type="conversation",
            outcome="failure",
            request_id="trace-shared",
        )

        assert await get_audit_event(session, tenant_id="tenant-b", event_id=first["id"]) is None
        detail = await get_audit_event(session, tenant_id="tenant-a", event_id=first["id"])
        trace = await list_request_audit_events(
            session,
            tenant_id="tenant-a",
            request_id="trace-shared",
        )

    assert detail is not None
    assert detail["id"] == first["id"]
    assert [item["id"] for item in trace] == [first["id"], second["id"]]
    assert {item["tenant_id"] for item in trace} == {"tenant-a"}


@pytest.mark.asyncio
async def test_conversation_history_is_scoped_and_preserves_public_messages(isolated_database: None) -> None:
    async with SessionFactory() as session:
        conversation = await ensure_conversation(
            session,
            thread_id="thread_scope_a",
            tenant_id="tenant-a",
            owner_id="user-a",
            title="差旅制度查询",
            attachment_count=1,
        )
        await append_conversation_message(
            session,
            conversation_id=conversation["id"],
            role="user",
            content="差旅标准是什么？",
            attachments=[{"name": "制度.pdf", "mime_type": "application/pdf"}],
        )
        await finish_conversation_turn(
            session,
            conversation_id=conversation["id"],
            status="completed",
            role="assistant",
            content="请按企业差旅制度执行。",
            references=["差旅制度.pdf"],
        )
        await set_conversation_feedback(
            session,
            conversation_id=conversation["id"],
            user_id="user-a",
            rating="helpful",
        )

        await append_conversation_message(
            session,
            conversation_id=conversation["id"],
            role="user",
            content="再补充审批顺序。",
        )
        await finish_conversation_turn(
            session,
            conversation_id=conversation["id"],
            status="completed",
            role="assistant",
            content="先部门审批，再由财务复核。",
        )
        await set_conversation_feedback(
            session,
            conversation_id=conversation["id"],
            user_id="user-a",
            rating="not_helpful",
        )

        own = await get_user_conversation(
            session,
            thread_id="thread_scope_a",
            tenant_id="tenant-a",
            owner_id="user-a",
        )
        wrong_tenant = await get_user_conversation(
            session,
            thread_id="thread_scope_a",
            tenant_id="tenant-b",
            owner_id="user-a",
        )
        wrong_owner = await list_user_conversations(session, tenant_id="tenant-a", owner_id="user-b")
        feedback_records = list(
            (await session.scalars(select(ConversationFeedbackRecord))).all()
        )

    assert own is not None
    assert own["status"] == "completed"
    assert own["feedback"] == "not_helpful"
    assert [message["role"] for message in own["messages"]] == ["user", "assistant", "user", "assistant"]
    assert own["messages"][1]["references"] == ["差旅制度.pdf"]
    assert {record.rating for record in feedback_records} == {"helpful", "not_helpful"}
    assert wrong_tenant is None
    assert wrong_owner == []


@pytest.mark.asyncio
async def test_tenant_feedback_list_excludes_other_tenants_and_message_content(
    isolated_database: None,
) -> None:
    async with SessionFactory() as session:
        for tenant_id, user_id, rating in (
            ("tenant-a", "user-a", "helpful"),
            ("tenant-b", "user-b", "not_helpful"),
        ):
            conversation = await ensure_conversation(
                session,
                thread_id=f"thread-{tenant_id}",
                tenant_id=tenant_id,
                owner_id=user_id,
                title=f"{tenant_id} 敏感标题",
                attachment_count=0,
            )
            await finish_conversation_turn(
                session,
                conversation_id=conversation["id"],
                status="completed",
                role="assistant",
                content=f"{tenant_id} 敏感回答",
            )
            await set_conversation_feedback(
                session,
                conversation_id=conversation["id"],
                user_id=user_id,
                rating=rating,
            )

        records, window_complete = await list_tenant_conversation_feedback(
            session,
            tenant_id="tenant-a",
        )

    assert window_complete is True
    assert len(records) == 1
    assert records[0]["respondent_id"] == "user-a"
    assert records[0]["rating"] == "helpful"
    assert "title" not in records[0]
    assert "content" not in records[0]
    assert "message_id" not in records[0]


@pytest.mark.asyncio
async def test_chat_stream_persists_user_visible_conversation(
    isolated_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = CurrentUser(
        user_id="user-a",
        username="tester",
        tenant_id="tenant-a",
        role="user",
        permissions=["chat:use"],
        groups=[],
        access_token="token",
    )

    async def no_rate_limit(*args, **kwargs):
        return None

    async def no_audit(*args, **kwargs):
        return None

    async def fake_stream(*args, **kwargs):
        yield {"type": "status", "message": "正在处理"}
        yield {"type": "complete", "message": "已完成回答", "references": ["制度.pdf"]}

    monkeypatch.setattr(main, "_rate_limit", no_rate_limit)
    monkeypatch.setattr(main, "append_audit_event", no_audit)
    monkeypatch.setattr(main, "run_agent_stream", fake_stream)
    monkeypatch.setattr(main.app.state, "checkpointer", object(), raising=False)

    async with SessionFactory() as session:
        response = await main.chat_endpoint(
            main.ChatRequest(query="请查询制度", thread_id="thread_test_1"),
            user,
            session,
        )
        async for _ in response.body_iterator:
            pass

    async with SessionFactory() as session:
        detail = await get_user_conversation(
            session,
            thread_id="thread_test_1",
            tenant_id="tenant-a",
            owner_id="user-a",
        )

    assert detail is not None
    assert detail["status"] == "completed"
    assert [message["content"] for message in detail["messages"]] == ["请查询制度", "已完成回答"]
    assert detail["messages"][1]["references"] == ["制度.pdf"]


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
