from __future__ import annotations

from pathlib import Path

import pytest

from config import settings
from multi_domain_enterprise_project.api import worker_runtime
from multi_domain_enterprise_project.core.auth import CurrentUser
from multi_domain_enterprise_project.core.database import (
    SessionFactory,
    close_database,
    create_document,
    create_job,
    init_database,
    reconfigure_database,
    update_job,
)


@pytest.fixture
async def isolated_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings.runtime, "environment", "test")
    await reconfigure_database(f"sqlite+aiosqlite:///{tmp_path / 'worker-runtime.db'}")
    await init_database()
    yield
    await close_database()


def _reader() -> CurrentUser:
    return CurrentUser(
        user_id="platform-admin",
        username="admin",
        tenant_id="tenant-a",
        role="admin",
        permissions=["audit:read", "kb:read"],
        groups=[],
        access_token="token",
    )


def _document(document_id: str, tenant_id: str) -> dict:
    return {
        "id": document_id,
        "file_name": f"{document_id}.pdf",
        "title": "企业制度",
        "tenant_id": tenant_id,
        "owner_id": "owner-1",
        "acl": ["finance"],
        "file_path": f"/controlled/{document_id}.pdf",
        "checksum": "a" * 64,
    }


@pytest.mark.asyncio
async def test_worker_runtime_combines_queue_and_tenant_jobs(
    isolated_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_queue() -> worker_runtime.QueueSnapshot:
        return worker_runtime.QueueSnapshot(
            available=True,
            group_initialized=True,
            stream_length=7,
            dead_letter_length=1,
            pending=2,
            lag=3,
            consumers=[worker_runtime.WorkerConsumer(name="worker-1", pending=2, idle_ms=1200)],
        )

    monkeypatch.setattr(worker_runtime, "_read_queue_snapshot", fake_queue)

    async with SessionFactory() as session:
        await create_document(session, _document("doc-a", "tenant-a"))
        await create_document(session, _document("doc-b", "tenant-b"))
        own = await create_job(
            session,
            job_id="job-a",
            document_id="doc-a",
            tenant_id="tenant-a",
            operation="ingest",
            mode="mg",
            requested_by="owner-1",
            request_id="request-a",
        )
        await update_job(session, own.id, status="processing", attempts=1)
        await create_job(
            session,
            job_id="job-b",
            document_id="doc-b",
            tenant_id="tenant-b",
            operation="ingest",
            mode="graph",
            requested_by="owner-2",
            request_id="request-b",
        )

        response = await worker_runtime.get_worker_runtime(_reader(), session)

    assert response.queue.stream_length == 7
    assert response.queue.pending == 2
    assert response.queue.consumers[0].name == "worker-1"
    assert [(item.status, item.count) for item in response.status_counts] == [("processing", 1)]
    assert [item.id for item in response.active_jobs] == ["job-a"]
    assert response.active_jobs[0].file_name == "doc-a.pdf"
