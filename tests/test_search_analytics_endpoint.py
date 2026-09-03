from __future__ import annotations

import pytest

from multi_domain_enterprise_project.api import search_analytics
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


def _event(
    event_id: str,
    action: str,
    *,
    metadata: dict | None = None,
    outcome: str | None = None,
) -> dict:
    return {
        "id": event_id,
        "tenant_id": "tenant-1",
        "actor_id": "user-1",
        "actor_type": "user",
        "source": "api",
        "action": action,
        "resource_type": "knowledge_index",
        "resource_id": None,
        "outcome": outcome or ("success" if action == "search.completed" else "failure"),
        "request_id": f"request-{event_id}",
        "metadata": metadata or {},
        "occurred_at": f"2026-09-02T08:00:{event_id.zfill(2)}+00:00",
    }


@pytest.mark.asyncio
async def test_search_analytics_uses_tenant_window_and_measured_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    events = [
        _event("5", "audit.event_read"),
        _event("4", "search.completed", metadata={"mode": "mg", "elapsed_ms": 400, "result_count": 0, "input_digest": "secret-digest"}),
        _event("3", "search.completed", metadata={"mode": "milvus", "elapsed_ms": 100, "result_count": 4}),
        _event("2", "search.failed", metadata={"mode": "mg", "error_type": "TimeoutError"}),
        _event("1", "search.completed", metadata={"mode": "mg", "elapsed_ms": 200, "result_count": 2}),
    ]

    async def fake_events(session, **kwargs):
        captured["query"] = kwargs
        return events, "older-page"

    async def fake_audit(session, **kwargs):
        captured["audit"] = kwargs

    monkeypatch.setattr(search_analytics, "list_audit_events", fake_events)
    monkeypatch.setattr(search_analytics, "append_audit_event", fake_audit)

    response = await search_analytics.get_search_analytics(_reader(), object())

    assert captured["query"] == {"tenant_id": "tenant-1", "limit": 200}
    assert response.audit_window_size == 5
    assert response.audit_window_complete is False
    assert response.search_event_count == 4
    assert response.completed_count == 3
    assert response.failed_count == 1
    assert response.success_rate == 0.75
    assert response.latency.model_dump() == {
        "sample_count": 3,
        "average_ms": 233,
        "p50_ms": 200,
        "p95_ms": 400,
        "maximum_ms": 400,
    }
    assert response.results.model_dump() == {
        "sample_count": 3,
        "average_count": 2.0,
        "zero_result_count": 1,
        "zero_result_rate": pytest.approx(1 / 3),
    }
    assert [item.model_dump() for item in response.modes] == [
        {"id": "mg", "count": 3},
        {"id": "milvus", "count": 1},
    ]
    assert response.error_types[0].model_dump() == {"id": "TimeoutError", "count": 1}
    assert captured["audit"]["action"] == "search.analytics_read"
    assert captured["audit"]["metadata"]["window_complete"] is False


@pytest.mark.asyncio
async def test_search_analytics_does_not_treat_missing_or_invalid_values_as_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [
        _event("3", "search.completed", metadata={"mode": "mg"}),
        _event("2", "search.completed", metadata={"mode": "", "elapsed_ms": True, "result_count": -1}),
        _event("1", "search.failed", metadata={"error_type": ""}),
    ]

    async def fake_events(session, **kwargs):
        return events, None

    async def fake_audit(session, **kwargs):
        return None

    monkeypatch.setattr(search_analytics, "list_audit_events", fake_events)
    monkeypatch.setattr(search_analytics, "append_audit_event", fake_audit)

    response = await search_analytics.get_search_analytics(_reader(), object())

    assert response.latency.sample_count == 0
    assert response.latency.average_ms is None
    assert response.results.sample_count == 0
    assert response.results.zero_result_rate is None
    assert [item.model_dump() for item in response.modes] == [{"id": "mg", "count": 1}]
    assert response.error_types == []


@pytest.mark.asyncio
async def test_search_analytics_returns_whitelisted_event_fields_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [
        _event(
            "1",
            "search.completed",
            metadata={"mode": "graph", "elapsed_ms": 18, "result_count": 1, "input_digest": "must-not-leak"},
        )
    ]

    async def fake_events(session, **kwargs):
        return events, None

    async def fake_audit(session, **kwargs):
        return None

    monkeypatch.setattr(search_analytics, "list_audit_events", fake_events)
    monkeypatch.setattr(search_analytics, "append_audit_event", fake_audit)

    response = await search_analytics.get_search_analytics(_reader(), object())
    payload = response.model_dump()

    assert "metadata" not in payload["recent_events"][0]
    assert "input_digest" not in str(payload)
    assert payload["recent_events"][0]["mode"] == "graph"


@pytest.mark.asyncio
async def test_search_analytics_empty_window_has_no_invented_rates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_events(session, **kwargs):
        return [], None

    async def fake_audit(session, **kwargs):
        return None

    monkeypatch.setattr(search_analytics, "list_audit_events", fake_events)
    monkeypatch.setattr(search_analytics, "append_audit_event", fake_audit)

    response = await search_analytics.get_search_analytics(_reader(), object())

    assert response.search_event_count == 0
    assert response.success_rate is None
    assert response.results.zero_result_rate is None
    assert response.recent_events == []
