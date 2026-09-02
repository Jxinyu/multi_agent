from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from multi_domain_enterprise_project import main
from multi_domain_enterprise_project.api import conversations
from multi_domain_enterprise_project.core.auth import CurrentUser
from multi_domain_enterprise_project.core.search import (
    cache_search_evidence,
    get_cached_search_evidence,
    parse_retrieval_context,
)


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


async def _empty_conversations(*args, **kwargs):
    return []


class _MemoryPipeline:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values
        self.operations: list[tuple[str, str]] = []

    def set(self, key: str, value: str, **kwargs):
        self.operations.append((key, value))
        return self

    async def execute(self):
        for key, value in self.operations:
            self.values[key] = value
        return [True] * len(self.operations)


class _MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def pipeline(self, **kwargs):
        return _MemoryPipeline(self.values)

    async def get(self, key: str):
        return self.values.get(key)


def test_parse_retrieval_context_returns_structured_evidence() -> None:
    context = """### 融合检索参考资料：

--- [来源: 差旅制度.pdf | 后端: milvus, neo4j | 匹配分值: 0.8123 | 文档ID: abc123 | 版本: 3 | 切片: 7] ---
报销必须提交合法原始凭证。

--- [来源: 费用细则.pdf | 类型: 原始文本块 | 匹配分值: 0.7012] ---
电子发票需要完成验真。
"""

    items = parse_retrieval_context(context)

    assert [item["source"] for item in items] == ["差旅制度.pdf", "费用细则.pdf"]
    assert items[0]["backend"] == "milvus, neo4j"
    assert items[0]["score"] == pytest.approx(0.8123)
    assert items[0]["document_id"] == "abc123"
    assert items[0]["version"] == 3
    assert items[0]["chunk_index"] == 7
    assert items[1]["kind"] == "原始文本块"


@pytest.mark.asyncio
async def test_search_evidence_cache_is_scoped_by_tenant_and_user() -> None:
    redis = _MemoryRedis()
    item = {
        "id": "a" * 16,
        "source": "制度.pdf",
        "content": "命中内容",
        "score": 0.9,
        "kind": "原始文本块",
        "backend": "milvus",
    }

    await cache_search_evidence(
        redis,
        tenant_id="tenant-a",
        user_id="user-a",
        items=[item],
        ttl_seconds=900,
    )

    own = await get_cached_search_evidence(
        redis,
        tenant_id="tenant-a",
        user_id="user-a",
        evidence_id="a" * 16,
    )
    wrong_user = await get_cached_search_evidence(
        redis,
        tenant_id="tenant-a",
        user_id="user-b",
        evidence_id="a" * 16,
    )
    wrong_tenant = await get_cached_search_evidence(
        redis,
        tenant_id="tenant-b",
        user_id="user-a",
        evidence_id="a" * 16,
    )

    assert own == item
    assert wrong_user is None
    assert wrong_tenant is None


@pytest.mark.asyncio
async def test_search_endpoint_audits_hash_without_raw_query(monkeypatch: pytest.MonkeyPatch) -> None:
    audit_payload = {}
    cache_payload = {}

    async def no_rate_limit(*args, **kwargs):
        return None

    async def fake_retrieve(**kwargs):
        return "--- [来源: 制度.pdf | 类型: 原始文本块 | 匹配分值: 0.9] ---\n命中内容"

    async def capture_audit(session, **kwargs):
        audit_payload.update(kwargs)

    async def capture_cache(redis, **kwargs):
        cache_payload.update(kwargs)

    monkeypatch.setattr(main, "_rate_limit", no_rate_limit)
    monkeypatch.setattr(main, "retrieve_service", fake_retrieve)
    monkeypatch.setattr(main, "append_audit_event", capture_audit)
    monkeypatch.setattr(main, "cache_search_evidence", capture_cache)
    monkeypatch.setattr(main, "redis_conn", object())

    response = await main.api_search(main.SearchRequest(query="敏感查询", mode="mg"), _user(), object())

    assert response.items[0].source == "制度.pdf"
    assert audit_payload["metadata"]["input_digest"]
    assert "敏感查询" not in str(audit_payload)
    assert cache_payload["tenant_id"] == "tenant-1"
    assert cache_payload["user_id"] == "user-1"


@pytest.mark.asyncio
async def test_search_endpoint_maps_dependency_connection_failure_to_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_payload = {}

    async def no_rate_limit(*args, **kwargs):
        return None

    async def failed_retrieve(**kwargs):
        raise ConnectionError("ollama unavailable")

    async def capture_audit(session, **kwargs):
        audit_payload.update(kwargs)

    monkeypatch.setattr(main, "_rate_limit", no_rate_limit)
    monkeypatch.setattr(main, "retrieve_service", failed_retrieve)
    monkeypatch.setattr(main, "append_audit_event", capture_audit)

    with pytest.raises(HTTPException) as exc_info:
        await main.api_search(main.SearchRequest(query="敏感查询", mode="mg"), _user(), object())

    assert exc_info.value.status_code == 503
    assert audit_payload["action"] == "search.failed"
    assert audit_payload["metadata"] == {"error_type": "ConnectionError", "mode": "mg"}
    assert "敏感查询" not in str(audit_payload)


@pytest.mark.asyncio
async def test_search_evidence_detail_uses_current_user_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def fake_cached(redis, **kwargs):
        captured.update(kwargs)
        return {
            "id": "a" * 16,
            "source": "制度.pdf",
            "content": "命中内容",
            "score": 0.9,
            "kind": "原始文本块",
            "backend": "milvus",
        }

    async def no_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(main, "get_cached_search_evidence", fake_cached)
    monkeypatch.setattr(main, "append_audit_event", no_audit)
    monkeypatch.setattr(main, "redis_conn", object())

    response = await main.api_get_search_evidence("a" * 16, _user(), object())

    assert response.source == "制度.pdf"
    assert captured == {
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "evidence_id": "a" * 16,
    }


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

    monkeypatch.setattr(conversations, "list_audit_events", fake_list)
    monkeypatch.setattr(conversations, "list_user_conversations", _empty_conversations)

    response = await conversations.list_tasks(_user(), object())

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

    monkeypatch.setattr(conversations, "list_audit_events", fake_list)
    monkeypatch.setattr(conversations, "list_user_conversations", _empty_conversations)

    response = await conversations.list_tasks(_user(), object())

    assert response.items[0].status == "cancelled"


@pytest.mark.asyncio
async def test_task_endpoint_prefers_persisted_conversation_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list_events(*args, **kwargs):
        return ([{
            "action": "chat.requested",
            "resource_id": "thread-live",
            "occurred_at": "2026-09-02T10:00:00+00:00",
            "metadata": {},
        }], None)

    async def fake_conversations(*args, **kwargs):
        return [{
            "thread_id": "thread-live",
            "status": "completed",
            "created_at": "2026-09-02T10:00:00+00:00",
            "updated_at": "2026-09-02T10:01:00+00:00",
            "attachment_count": 0,
            "title": "持久化会话",
        }]

    monkeypatch.setattr(conversations, "list_audit_events", fake_list_events)
    monkeypatch.setattr(conversations, "list_user_conversations", fake_conversations)

    response = await conversations.list_tasks(_user(), object())

    assert len(response.items) == 1
    assert response.items[0].status == "completed"
    assert response.items[0].title == "持久化会话"
    assert response.items[0].detail_available is True


@pytest.mark.asyncio
async def test_task_detail_is_scoped_to_current_user(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def fake_conversation(session, **kwargs):
        captured.update(kwargs)
        return {
            "id": "conversation-id",
            "thread_id": "thread-detail",
            "status": "waiting",
            "title": "需要补充",
            "created_at": "2026-09-02T10:00:00+00:00",
            "updated_at": "2026-09-02T10:01:00+00:00",
            "attachment_count": 0,
            "waiting_prompt": "请补充系统名称",
            "feedback": None,
            "messages": [],
        }

    monkeypatch.setattr(conversations, "get_user_conversation", fake_conversation)

    response = await conversations.get_task("thread-detail", _user(), object())

    assert captured["tenant_id"] == "tenant-1"
    assert captured["owner_id"] == "user-1"
    assert response.waiting_prompt == "请补充系统名称"


@pytest.mark.asyncio
async def test_task_feedback_updates_scoped_conversation_and_audits(monkeypatch: pytest.MonkeyPatch) -> None:
    feedback_payload = {}
    audit_payload = {}

    async def fake_conversation(session, **kwargs):
        return {"id": "conversation-id"}

    async def fake_feedback(session, **kwargs):
        feedback_payload.update(kwargs)
        return True

    async def fake_audit(session, **kwargs):
        audit_payload.update(kwargs)

    monkeypatch.setattr(conversations, "get_user_conversation", fake_conversation)
    monkeypatch.setattr(conversations, "set_conversation_feedback", fake_feedback)
    monkeypatch.setattr(conversations, "append_audit_event", fake_audit)

    response = await conversations.set_task_feedback(
        "thread-detail",
        conversations.UserTaskFeedbackRequest(rating="not_helpful"),
        _user(),
        object(),
    )

    assert response == {"success": True, "rating": "not_helpful"}
    assert feedback_payload == {
        "conversation_id": "conversation-id",
        "user_id": "user-1",
        "rating": "not_helpful",
    }
    assert audit_payload["metadata"] == {"rating": "not_helpful"}


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


@pytest.mark.asyncio
async def test_user_document_detail_enforces_acl(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_document(session, document_id, tenant_id):
        return _document(document_id, "user-2", ["legal"])

    monkeypatch.setattr(main, "get_document", fake_get_document)

    with pytest.raises(HTTPException) as exc_info:
        await main.api_get_user_document("hidden", _user(), object())

    assert getattr(exc_info.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_user_document_detail_returns_safe_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    audit_payload = {}

    async def fake_get_document(session, document_id, tenant_id):
        item = _document(document_id, "user-1", ["private"])
        item["file_path_md"] = "server-only.md"
        return item

    async def fake_preview(item, *, max_chars):
        assert item["file_path_md"] == "server-only.md"
        return "解析正文", False

    async def capture_audit(session, **kwargs):
        audit_payload.update(kwargs)

    monkeypatch.setattr(main, "get_document", fake_get_document)
    monkeypatch.setattr(main, "read_document_preview", fake_preview)
    monkeypatch.setattr(main, "append_audit_event", capture_audit)

    response = await main.api_get_user_document("owned", _user(), object())

    assert response.preview == "解析正文"
    assert "file_path_md" not in response.item.model_dump()
    assert audit_payload["metadata"] == {"preview_available": True}
