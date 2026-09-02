from __future__ import annotations

import pytest
from fastapi import HTTPException

from multi_domain_enterprise_project.api import members, security
from multi_domain_enterprise_project.core.auth import CurrentUser


def _reader() -> CurrentUser:
    return CurrentUser(
        user_id="admin-1",
        username="admin",
        tenant_id="tenant-1",
        role="admin",
        permissions=["audit:read", "kb:read"],
        groups=["ops"],
        access_token="token",
    )


def _event(event_id: str, actor_id: str = "actor-2", action: str = "document.read") -> dict:
    return {
        "id": event_id,
        "tenant_id": "tenant-1",
        "actor_id": actor_id,
        "actor_type": "user",
        "source": "api",
        "action": action,
        "resource_type": "document",
        "resource_id": "doc-1",
        "outcome": "success",
        "request_id": "trace-1",
        "metadata": {"result_count": 1},
        "occurred_at": "2026-09-02T08:00:00+00:00",
    }


@pytest.mark.asyncio
async def test_member_detail_only_returns_claims_for_current_user(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_events(session, **kwargs):
        actor_id = kwargs["actor_id"]
        return ([_event("event-1", actor_id=actor_id)], None)

    monkeypatch.setattr(members, "list_audit_events", fake_events)

    current = await members.get_observed_member("admin-1", _reader(), object())
    observed = await members.get_observed_member("actor-2", _reader(), object())

    assert current.role == "admin"
    assert current.permissions == ["audit:read", "kb:read"]
    assert current.groups == ["ops"]
    assert observed.role is None
    assert observed.permissions == []
    assert observed.groups == []
    assert observed.identity_source == "租户审计事件"


@pytest.mark.asyncio
async def test_member_detail_rejects_unobserved_non_current_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_events(session, **kwargs):
        return ([], None)

    monkeypatch.setattr(members, "list_audit_events", fake_events)

    with pytest.raises(HTTPException) as exc_info:
        await members.get_observed_member("missing", _reader(), object())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_security_detail_returns_same_request_trace_and_audits_read(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    item = _event("event-1")
    related = [item, _event("event-2", action="document.completed")]

    async def fake_get(session, **kwargs):
        captured["get"] = kwargs
        return item

    async def fake_trace(session, **kwargs):
        captured["trace"] = kwargs
        return related

    async def fake_append(session, **kwargs):
        captured["audit"] = kwargs
        return {}

    monkeypatch.setattr(security, "get_audit_event", fake_get)
    monkeypatch.setattr(security, "list_request_audit_events", fake_trace)
    monkeypatch.setattr(security, "append_audit_event", fake_append)

    response = await security.get_audit_event_detail("event-1", _reader(), object())

    assert captured["get"] == {"tenant_id": "tenant-1", "event_id": "event-1"}
    assert captured["trace"]["tenant_id"] == "tenant-1"
    assert captured["trace"]["request_id"] == "trace-1"
    assert captured["audit"]["action"] == "audit.event_read"
    assert [event.id for event in response.related_events] == ["event-1", "event-2"]


@pytest.mark.asyncio
async def test_security_detail_rejects_missing_event(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(session, **kwargs):
        return None

    monkeypatch.setattr(security, "get_audit_event", fake_get)

    with pytest.raises(HTTPException) as exc_info:
        await security.get_audit_event_detail("missing", _reader(), object())

    assert exc_info.value.status_code == 404
