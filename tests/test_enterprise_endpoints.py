from __future__ import annotations

import pytest
from fastapi import HTTPException

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


@pytest.mark.asyncio
async def test_runtime_agent_detail_uses_published_catalog_and_live_connections() -> None:
    response = await enterprise.get_runtime_agent_detail("tech", _reader())

    assert response.label == "技术智能体"
    assert response.model_name == "qwen-plus"
    assert response.tool_call_limit == 4
    assert response.summarization_trigger_messages == 8
    assert response.source_module.endswith("tech_agent.tech_agent_node")
    assert [item.id for item in response.connections] == ["rag", "web"]
    assert response.connections[0].configured is True
    assert response.editable is False


@pytest.mark.asyncio
async def test_runtime_agent_detail_rejects_unknown_agent() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await enterprise.get_runtime_agent_detail("unknown", _reader())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_connection_detail_probes_configured_endpoint_and_hides_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 405

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, url):
            captured["url"] = url
            return FakeResponse()

    async def fake_audit(session, **kwargs):
        captured["audit"] = kwargs

    monkeypatch.setattr(
        enterprise.settings.mcp,
        "rag_url",
        "https://mcp.local:8010/opaque-segment-12345/rag?ref=sample-value",
    )
    monkeypatch.setattr(enterprise.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(enterprise, "append_audit_event", fake_audit)

    response = await enterprise.get_runtime_connection_detail("rag", _reader(), object())

    assert response.health == "healthy"
    assert response.http_status == 405
    assert response.endpoint_hint == "https://mcp.local:8010/…"
    assert "opaque-segment-12345" not in response.model_dump_json()
    assert "sample-value" not in response.model_dump_json()
    assert {item.id for item in response.affected_agents} == {"finance", "tech", "legal", "hr"}
    assert captured["client"] == {"timeout": 5, "trust_env": False}
    assert captured["audit"]["metadata"]["health"] == "healthy"


@pytest.mark.asyncio
async def test_connection_detail_marks_missing_configuration_without_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_probe(url):
        raise AssertionError("未配置连接不应执行网络请求")

    async def fake_audit(session, **kwargs):
        return None

    monkeypatch.setattr(enterprise.settings.mcp, "legal_url", "")
    monkeypatch.setattr(enterprise, "_probe_connection", fail_probe)
    monkeypatch.setattr(enterprise, "append_audit_event", fake_audit)

    response = await enterprise.get_runtime_connection_detail("legal", _reader(), object())

    assert response.health == "unconfigured"
    assert response.configured is False
    assert response.http_status is None
    assert response.latency_ms is None
    assert response.endpoint_hint == "未配置"


@pytest.mark.asyncio
async def test_connection_detail_rejects_unknown_connection() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await enterprise.get_runtime_connection_detail("unknown", _reader(), object())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_evaluation_run_detail_reads_versioned_holdout_metrics() -> None:
    response = await enterprise.get_evaluation_run_detail(
        "rag_lambdamart_enriched_train1300_dev200_20260707", _reader(),
    )

    assert response.sample_count == 755
    assert response.split == "独立 Holdout"
    assert not response.source.startswith(("C:\\", "D:\\", "/"))
    current = next(item for item in response.variants if item.role == "当前方案")
    recall = next(item for item in current.values if item.id == "recall_at_10")
    assert recall.value == pytest.approx(0.9661)


@pytest.mark.asyncio
async def test_evaluation_run_detail_sanitizes_public_result_metadata() -> None:
    response = await enterprise.get_evaluation_run_detail("pubtables_public_50_20260707", _reader())

    assert response.dataset == "docling-project/PubTables-1M_OTSL-v1.1"
    assert response.sample_count == 50
    serialized = response.model_dump_json()
    assert "result_dir" not in serialized
    assert "report_path" not in serialized
    assert "D:\\" not in serialized


@pytest.mark.asyncio
async def test_evaluation_run_detail_rejects_unknown_run() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await enterprise.get_evaluation_run_detail("missing-run", _reader())

    assert exc_info.value.status_code == 404
