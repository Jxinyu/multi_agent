from __future__ import annotations

from datetime import UTC, datetime

import pytest

from multi_domain_enterprise_project import main
from multi_domain_enterprise_project.core.auth import CurrentUser
from multi_domain_enterprise_project.core.search import parse_retrieval_context


def _user() -> CurrentUser:
    return CurrentUser(
        user_id="user-1",
        username="tester",
        tenant_id="tenant-1",
        role="user",
        permissions=["chat:use", "kb:read"],
        groups=["private", "finance"],
        access_token="token",
    )


def _document(document_id: str, owner_id: str, acl: list[str]) -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "id": document_id,
        "file_name": f"{document_id}.pdf",
        "title": document_id,
        "tenant_id": "tenant-1",
        "owner_id": owner_id,
        "acl": acl,
        "upload_time": now,
        "mode": "rag",
        "status": "completed",
        "chunk_count": 3,
        "version": 1,
        "checksum": document_id,
        "backend_status": {},
    }


def test_parse_retrieval_context_returns_structured_evidence() -> None:
    context = """### 融合检索参考资料：

--- [来源: 差旅制度.pdf | 后端: milvus, neo4j | 匹配分值: 0.8123] ---
报销必须提交合法原始凭证。

--- [来源: 费用细则.pdf | 类型: 原始文本块 | 匹配分值: 0.7012] ---
电子发票需要完成验真。
"""

    items = parse_retrieval_context(context)

    assert [item["source"] for item in items] == ["差旅制度.pdf", "费用细则.pdf"]
    assert items[0]["backend"] == "milvus, neo4j"
    assert items[0]["score"] == pytest.approx(0.8123)
    assert items[1]["kind"] == "原始文本块"


@pytest.mark.asyncio
async def test_search_endpoint_audits_hash_without_raw_query(monkeypatch: pytest.MonkeyPatch) -> None:
    audit_payload = {}

    async def no_rate_limit(*args, **kwargs):
        return None

    async def fake_retrieve(**kwargs):
        return "--- [来源: 制度.pdf | 类型: 原始文本块 | 匹配分值: 0.9] ---\n命中内容"

    async def capture_audit(session, **kwargs):
        audit_payload.update(kwargs)

    monkeypatch.setattr(main, "_rate_limit", no_rate_limit)
    monkeypatch.setattr(main, "retrieve_service", fake_retrieve)
    monkeypatch.setattr(main, "append_audit_event", capture_audit)

    response = await main.api_search(main.SearchRequest(query="敏感查询", mode="mg"), _user(), object())

    assert response.items[0].source == "制度.pdf"
    assert audit_payload["metadata"]["input_digest"]
    assert "敏感查询" not in str(audit_payload)


@pytest.mark.asyncio
async def test_task_endpoint_is_scoped_to_current_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def fake_list(session, **kwargs):
        captured.update(kwargs)
        return ([
            {
                "action": "chat.completed",
                "resource_id": "thread-1",
                "occurred_at": "2026-08-29T10:01:00+00:00",
                "metadata": {},
            },
            {
                "action": "chat.requested",
                "resource_id": "thread-1",
                "occurred_at": "2026-08-29T10:00:00+00:00",
                "metadata": {"attachment_count": 2},
            },
        ], None)

    monkeypatch.setattr(main, "list_audit_events", fake_list)

    response = await main.api_list_user_tasks(_user(), object())

    assert captured["actor_id"] == "user-1"
    assert captured["tenant_id"] == "tenant-1"
    assert response.items[0].status == "completed"
    assert response.items[0].attachment_count == 2


@pytest.mark.asyncio
async def test_task_endpoint_marks_stale_running_task_as_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list(session, **kwargs):
        return ([
            {
                "action": "chat.requested",
                "resource_id": "thread-stale",
                "occurred_at": "2026-01-01T10:00:00+00:00",
                "metadata": {},
            }
        ], None)

    monkeypatch.setattr(main, "list_audit_events", fake_list)

    response = await main.api_list_user_tasks(_user(), object())

    assert response.items[0].status == "cancelled"


@pytest.mark.asyncio
async def test_user_documents_filter_owner_and_acl(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_documents(session, tenant_id):
        return [
            _document("owned", "user-1", ["private"]),
            _document("shared", "user-2", ["finance"]),
            _document("hidden", "user-2", ["legal"]),
        ]

    monkeypatch.setattr(main, "list_documents", fake_documents)

    response = await main.api_list_user_documents(_user(), object())

    assert [item.id for item in response.items] == ["owned", "shared"]
