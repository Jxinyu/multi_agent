from __future__ import annotations

import pytest

from multi_domain_enterprise_project.api import enterprise
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


@pytest.mark.asyncio
async def test_enterprise_overview_uses_tenant_scoped_events(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def fake_events(session, **kwargs):
        captured.update(kwargs)
        return ([
            {"id": "3", "actor_id": "u1", "action": "search.completed", "resource_id": None, "metadata": {"elapsed_ms": 120}, "occurred_at": "2026-08-29T10:03:00+00:00"},
            {"id": "2", "actor_id": "u1", "action": "chat.completed", "resource_id": "t1", "metadata": {}, "occurred_at": "2026-08-29T10:02:00+00:00"},
            {"id": "1", "actor_id": "u2", "action": "chat.requested", "resource_id": "t1", "metadata": {}, "occurred_at": "2026-08-29T10:01:00+00:00"},
        ], None)

    async def fake_documents(session, tenant_id):
        return [{"status": "completed"}, {"status": "failed"}]

    monkeypatch.setattr(enterprise, "list_audit_events", fake_events)
    monkeypatch.setattr(enterprise, "list_documents", fake_documents)

    response = await enterprise.get_enterprise_overview(_reader(), object())

    assert captured["tenant_id"] == "tenant-1"
    assert response.observed_actors == ["u1", "u2"]
    assert response.conversation_count == 1
    assert response.completed_count == 1
    assert response.running_count == 0
    assert response.average_search_ms == 120
    assert response.healthy_document_count == 1


@pytest.mark.asyncio
async def test_enterprise_overview_marks_stale_requested_chat_as_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_events(session, **kwargs):
        return ([
            {"id": "1", "actor_id": "u1", "action": "chat.requested", "resource_id": "stale", "metadata": {}, "occurred_at": "2020-01-01T00:00:00Z"},
        ], None)

    async def fake_documents(session, tenant_id):
        return []

    monkeypatch.setattr(enterprise, "list_audit_events", fake_events)
    monkeypatch.setattr(enterprise, "list_documents", fake_documents)

    response = await enterprise.get_enterprise_overview(_reader(), object())

    assert response.failed_count == 1
    assert response.running_count == 0


@pytest.mark.asyncio
async def test_evaluation_summary_reads_versioned_metric_files() -> None:
    response = await enterprise.get_evaluation_summary(_reader())
    metrics = {metric.id: metric for metric in response.metrics}

    assert metrics["routing_accuracy"].baseline == pytest.approx(0.8083)
    assert metrics["routing_accuracy"].current == pytest.approx(0.9667)
    assert metrics["recall_at_10"].current == pytest.approx(0.9661)
    assert metrics["pubtables_retention"].sample_count == 50
    assert metrics["cloud_calls"].baseline == 30
    assert metrics["cloud_calls"].current == 0


@pytest.mark.asyncio
async def test_runtime_summary_only_marks_configured_connections() -> None:
    response = await enterprise.get_runtime_summary(_reader())

    assert {agent.id for agent in response.agents} == {"finance", "tech", "legal", "hr"}
    rag = next(item for item in response.connections if item.id == "rag")
    assert rag.configured is True
