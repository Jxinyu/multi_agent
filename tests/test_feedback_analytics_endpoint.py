from __future__ import annotations

import pytest

from multi_domain_enterprise_project.api import feedback_analytics
from multi_domain_enterprise_project.core.auth import CurrentUser


def _reader() -> CurrentUser:
    return CurrentUser(
        user_id="admin-1",
        username="admin",
        tenant_id="tenant-1",
        role="admin",
        permissions=["audit:read", "kb:read"],
        groups=["tenant"],
        access_token="token",
    )


def _record(record_id: str, *, rating: str, respondent: str, status: str) -> dict:
    return {
        "id": record_id,
        "conversation_id": f"conversation-{record_id}",
        "thread_id": f"thread-{record_id}",
        "respondent_id": respondent,
        "conversation_status": status,
        "rating": rating,
        "created_at": "2026-09-03T08:00:00+00:00",
        "updated_at": "2026-09-03T08:01:00+00:00",
        "conversation_updated_at": "2026-09-03T08:02:00+00:00",
    }


@pytest.mark.asyncio
async def test_feedback_analytics_uses_tenant_window_and_current_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    records = [
        _record("3", rating="helpful", respondent="user-a", status="completed"),
        _record("2", rating="not_helpful", respondent="user-b", status="failed"),
        _record("1", rating="helpful", respondent="user-a", status="completed"),
    ]

    async def fake_records(session, **kwargs):
        captured["query"] = kwargs
        return records, False

    async def fake_audit(session, **kwargs):
        captured["audit"] = kwargs

    monkeypatch.setattr(feedback_analytics, "list_tenant_conversation_feedback", fake_records)
    monkeypatch.setattr(feedback_analytics, "append_audit_event", fake_audit)

    response = await feedback_analytics.get_feedback_analytics(_reader(), object())

    assert captured["query"] == {"tenant_id": "tenant-1", "limit": 200}
    assert response.feedback_count == 3
    assert response.helpful_count == 2
    assert response.not_helpful_count == 1
    assert response.helpful_rate == pytest.approx(2 / 3)
    assert response.respondent_count == 2
    assert response.average_per_respondent == 1.5
    assert response.window_complete is False
    assert [item.model_dump() for item in response.ratings] == [
        {"id": "helpful", "count": 2},
        {"id": "not_helpful", "count": 1},
    ]
    assert [item.model_dump() for item in response.conversation_statuses] == [
        {"id": "completed", "count": 2},
        {"id": "failed", "count": 1},
    ]
    assert captured["audit"]["action"] == "feedback.analytics_read"
    assert captured["audit"]["metadata"]["window_complete"] is False


@pytest.mark.asyncio
async def test_feedback_analytics_returns_whitelisted_metadata_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record("1", rating="helpful", respondent="user-a", status="completed")
    record.update({"title": "敏感问题", "content": "敏感回答", "message_id": "message-secret"})

    async def fake_records(session, **kwargs):
        return [record], True

    async def fake_audit(session, **kwargs):
        return None

    monkeypatch.setattr(feedback_analytics, "list_tenant_conversation_feedback", fake_records)
    monkeypatch.setattr(feedback_analytics, "append_audit_event", fake_audit)

    payload = (await feedback_analytics.get_feedback_analytics(_reader(), object())).model_dump()

    assert "title" not in payload["recent_feedback"][0]
    assert "content" not in payload["recent_feedback"][0]
    assert "message_id" not in payload["recent_feedback"][0]
    assert "敏感问题" not in str(payload)


@pytest.mark.asyncio
async def test_feedback_analytics_empty_window_has_no_invented_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_records(session, **kwargs):
        return [], True

    async def fake_audit(session, **kwargs):
        return None

    monkeypatch.setattr(feedback_analytics, "list_tenant_conversation_feedback", fake_records)
    monkeypatch.setattr(feedback_analytics, "append_audit_event", fake_audit)

    response = await feedback_analytics.get_feedback_analytics(_reader(), object())

    assert response.feedback_count == 0
    assert response.helpful_rate is None
    assert response.average_per_respondent is None
    assert response.recent_feedback == []
