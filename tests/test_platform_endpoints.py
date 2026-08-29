from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

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
async def test_runtime_status_preserves_probe_details(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_checks():
        return [SimpleNamespace(name="redis", ok=True, detail="ping ok")]

    monkeypatch.setattr(platform, "run_checks", fake_checks)
    response = await platform.get_runtime_status(_admin())

    assert response.services[0].name == "redis"
    assert response.services[0].ok is True
    assert response.maintenance_operations_enabled is False


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
