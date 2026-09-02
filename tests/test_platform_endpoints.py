from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from multi_domain_enterprise_project.api import platform
from multi_domain_enterprise_project.core.auth import CurrentUser


def _admin() -> CurrentUser:
    return CurrentUser(
        user_id="platform-admin",
        username="admin",
        tenant_id="tenant-a",
        role="admin",
        permissions=["audit:read", "kb:read"],
        groups=["platform"],
        access_token="token",
    )


@pytest.mark.asyncio
async def test_tenant_directory_only_reports_observed_real_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_events(session, **kwargs):
        return ([{"actor_id": "u1"}, {"actor_id": "u2"}, {"actor_id": "u1"}], None)

    async def fake_documents(session, tenant_id):
        return [{"status": "completed"}, {"status": "failed"}]

    monkeypatch.setattr(platform, "list_audit_events", fake_events)
    monkeypatch.setattr(platform, "list_documents", fake_documents)

    response = await platform.get_tenant_directory(_admin(), object())

    assert response.registry_available is False
    assert len(response.items) == 1
    assert response.items[0].tenant_id == "tenant-a"
    assert response.items[0].observed_users == 2
    assert response.items[0].healthy_document_count == 1
    assert response.items[0].vector_storage_quota_bytes is None


@pytest.mark.asyncio
async def test_tenant_detail_is_scoped_and_uses_observed_data(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_events(session, **kwargs):
        captured["event_scope"] = kwargs
        return ([
            {
                "id": "event-1",
                "tenant_id": "tenant-a",
                "actor_id": "user-1",
                "actor_type": "user",
                "source": "api",
                "action": "document.read",
                "resource_type": "document",
                "resource_id": "doc-1",
                "outcome": "success",
                "request_id": "request-1",
                "metadata": {},
                "occurred_at": "2026-09-02T08:00:00+00:00",
            },
        ], None)

    async def fake_documents(session, tenant_id):
        captured["document_scope"] = tenant_id
        return [{
            "id": "doc-1",
            "file_name": "制度.pdf",
            "owner_id": "user-1",
            "status": "completed",
            "mode": "graph",
            "upload_time": "2026-09-02T07:00:00+00:00",
        }]

    async def fake_append(session, **kwargs):
        captured["audit"] = kwargs

    monkeypatch.setattr(platform, "list_audit_events", fake_events)
    monkeypatch.setattr(platform, "list_documents", fake_documents)
    monkeypatch.setattr(platform, "append_audit_event", fake_append)

    response = await platform.get_tenant_detail("tenant-a", _admin(), object())

    assert captured["event_scope"] == {"tenant_id": "tenant-a", "limit": 200}
    assert captured["document_scope"] == "tenant-a"
    assert response.usage.observed_users == 1
    assert response.document_statuses[0].id == "completed"
    assert response.frequent_actions[0].id == "document.read"
    assert response.audit_window_complete is True
    assert captured["audit"]["resource_id"] == "tenant-a"

    with pytest.raises(HTTPException) as exc_info:
        await platform.get_tenant_detail("tenant-b", _admin(), object())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_runtime_status_preserves_probe_details(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_checks():
        return [SimpleNamespace(name="redis", ok=True, detail="ping ok")]

    monkeypatch.setattr(platform, "run_checks", fake_checks)
    response = await platform.get_runtime_status(_admin())

    assert response.services[0].name == "redis"
    assert response.services[0].ok is True
    assert response.maintenance_operations_enabled is False


@pytest.mark.asyncio
async def test_service_probe_detail_runs_only_registered_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_checks(names):
        captured["names"] = names
        return [SimpleNamespace(name="redis", ok=True, detail="ping ok")]

    async def fake_append(session, **kwargs):
        captured["audit"] = kwargs

    monkeypatch.setattr(platform, "run_checks", fake_checks)
    monkeypatch.setattr(platform, "append_audit_event", fake_append)

    response = await platform.get_service_probe_detail("redis", _admin(), object())

    assert captured["names"] == {"redis"}
    assert response.service.ok is True
    assert response.method == "PING"
    assert response.timeout_seconds == 3
    assert response.history_available is False
    assert captured["audit"]["metadata"] == {"probe_ok": True}

    with pytest.raises(HTTPException) as exc_info:
        await platform.get_service_probe_detail("unknown", _admin(), object())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_model_inventory_marks_transport_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(platform.httpx, "AsyncClient", lambda **kwargs: BrokenClient())
    response = await platform.get_model_inventory(_admin())

    assert response.connected is False
    assert response.models == []
    assert "ConnectError" in (response.error or "")


@pytest.mark.asyncio
async def test_platform_settings_do_not_expose_secrets() -> None:
    response = await platform.get_platform_settings(_admin())
    keys = {item.key for group in response.groups for item in group.items}

    assert response.mutable is False
    assert "password" not in keys
    assert "private_key_path" not in keys
    assert "llamaParse" not in keys
