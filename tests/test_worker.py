from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from config import settings
from multi_domain_enterprise_project.core.database import (
    IngestionJobRecord,
    SessionFactory,
    close_database,
    create_document,
    create_job,
    get_document,
    init_database,
    reconfigure_database,
    update_document,
)
from multi_domain_enterprise_project.core.jobs import DEAD_LETTER_STREAM, JOB_STREAM
from multi_domain_enterprise_project.worker import OPERATIONS, StreamMessage, process_message


class FakeRedis:
    def __init__(self) -> None:
        self.added: list[tuple[str, dict[str, str]]] = []
        self.acked: list[str] = []

    async def xadd(self, stream: str, fields: dict[str, str]) -> str:
        self.added.append((stream, fields))
        return f"{len(self.added)}-0"

    async def xack(self, _stream: str, _group: str, message_id: str) -> int:
        self.acked.append(message_id)
        return 1


@pytest.fixture
async def worker_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings.runtime, "environment", "test")
    monkeypatch.setattr(settings.runtime, "worker_max_attempts", 2)
    await reconfigure_database(f"sqlite+aiosqlite:///{tmp_path / 'worker.db'}")
    await init_database()
    async with SessionFactory() as session:
        await create_document(
            session,
            {
                "id": "d" * 32,
                "file_name": "policy.pdf",
                "title": "制度",
                "tenant_id": "tenant-a",
                "owner_id": "owner-a",
                "acl": ["private"],
                "file_path": str(tmp_path / "policy.pdf"),
                "checksum": "d" * 64,
                "status": "queued",
            },
        )
        await create_job(
            session,
            job_id="j" * 32,
            document_id="d" * 32,
            tenant_id="tenant-a",
            operation="ingest",
            mode="milvus",
        )
    yield
    await close_database()


def job_fields(attempts: int) -> dict[str, str]:
    return {
        "job_id": "j" * 32,
        "document_id": "d" * 32,
        "tenant_id": "tenant-a",
        "operation": "ingest",
        "mode": "milvus",
        "attempts": str(attempts),
    }


@pytest.mark.asyncio
async def test_worker_retries_then_moves_job_to_dead_letter(
    worker_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_operation(_item: dict[str, Any], _mode: str) -> None:
        raise RuntimeError("backend unavailable")

    monkeypatch.setitem(OPERATIONS, "ingest", fail_operation)
    redis = FakeRedis()

    await process_message(redis, StreamMessage("1-0", job_fields(0)))  # type: ignore[arg-type]
    async with SessionFactory() as session:
        first_job = await session.get(IngestionJobRecord, "j" * 32)
        first_document = await get_document(session, "d" * 32, "tenant-a")
    assert first_job is not None and first_job.status == "queued" and first_job.attempts == 1
    assert first_document is not None and first_document["status"] == "queued"
    assert redis.added[0][0] == JOB_STREAM

    await process_message(redis, StreamMessage("2-0", job_fields(1)))  # type: ignore[arg-type]
    async with SessionFactory() as session:
        final_job = await session.get(IngestionJobRecord, "j" * 32)
        final_document = await get_document(session, "d" * 32, "tenant-a")
    assert final_job is not None and final_job.status == "failed" and final_job.attempts == 2
    assert final_document is not None and final_document["status"] == "failed"
    assert redis.added[-1][0] == DEAD_LETTER_STREAM
    assert redis.acked == ["1-0", "2-0"]


@pytest.mark.asyncio
async def test_worker_marks_successful_job_and_acknowledges_message(
    worker_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def successful_operation(item: dict[str, Any], _mode: str) -> None:
        async with SessionFactory() as session:
            await update_document(session, item["id"], item["tenant_id"], status="ready")

    monkeypatch.setitem(OPERATIONS, "ingest", successful_operation)
    redis = FakeRedis()
    await process_message(redis, StreamMessage("3-0", job_fields(0)))  # type: ignore[arg-type]

    async with SessionFactory() as session:
        job = await session.get(IngestionJobRecord, "j" * 32)
        document = await get_document(session, "d" * 32, "tenant-a")
    assert job is not None and job.status == "succeeded" and job.attempts == 1
    assert document is not None and document["status"] == "ready"
    assert redis.acked == ["3-0"]

