from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from multi_domain_enterprise_project.api import files
from multi_domain_enterprise_project.core import document_files
from multi_domain_enterprise_project.core.auth import CurrentUser


def _user(*, user_id: str = "user-1", groups: list[str] | None = None) -> CurrentUser:
    return CurrentUser(
        user_id=user_id,
        username=user_id,
        tenant_id="tenant-a",
        role="user",
        permissions=["kb:read"],
        groups=groups or [],
        access_token="token",
    )


def _item(path: Path, *, owner_id: str = "user-1", acl: list[str] | None = None) -> dict:
    return {
        "id": "doc-1",
        "tenant_id": "tenant-a",
        "owner_id": owner_id,
        "acl": acl or ["private"],
        "file_name": path.name,
        "file_path": str(path),
    }


@pytest.mark.asyncio
async def test_user_document_preview_enforces_acl_and_audits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "policy.md"
    source.write_text("# Policy", encoding="utf-8")
    captured: dict[str, object] = {}

    async def fake_get_document(session, document_id, tenant_id):
        captured["scope"] = (document_id, tenant_id)
        return _item(source)

    async def fake_append(session, **kwargs):
        captured["audit"] = kwargs

    monkeypatch.setattr(document_files, "FILES_ROOT", tmp_path)
    monkeypatch.setattr(files, "get_document", fake_get_document)
    monkeypatch.setattr(files, "append_audit_event", fake_append)

    response = await files.get_user_document_content(
        "doc-1",
        current_user=_user(),
        session=object(),
        purpose="preview",
    )

    assert captured["scope"] == ("doc-1", "tenant-a")
    assert Path(response.path).resolve() == source.resolve()
    assert response.media_type == "text/markdown; charset=utf-8"
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.headers["cache-control"] == "private, no-store"
    assert captured["audit"]["action"] == "document.original_preview"
    assert captured["audit"]["metadata"]["extension"] == ".md"


@pytest.mark.asyncio
async def test_user_document_content_hides_unauthorized_document(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "private.pdf"
    source.write_bytes(b"%PDF-1.7")

    async def fake_get_document(session, document_id, tenant_id):
        return _item(source, owner_id="other-user")

    monkeypatch.setattr(document_files, "FILES_ROOT", tmp_path)
    monkeypatch.setattr(files, "get_document", fake_get_document)

    with pytest.raises(HTTPException) as exc_info:
        await files.get_user_document_content(
            "doc-1",
            current_user=_user(),
            session=object(),
            purpose="preview",
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_enterprise_download_uses_tenant_scope_and_attachment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "finance.xlsx"
    source.write_bytes(b"office-content")

    async def fake_get_document(session, document_id, tenant_id):
        return _item(source, owner_id="other-user")

    async def fake_append(session, **kwargs):
        return None

    monkeypatch.setattr(document_files, "FILES_ROOT", tmp_path)
    monkeypatch.setattr(files, "get_document", fake_get_document)
    monkeypatch.setattr(files, "append_audit_event", fake_append)

    response = await files.get_enterprise_document_content(
        "doc-1",
        current_user=_user(),
        session=object(),
        purpose="download",
    )

    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.media_type.endswith("spreadsheetml.sheet")


@pytest.mark.asyncio
async def test_document_content_rejects_path_outside_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    async def fake_get_document(session, document_id, tenant_id):
        return _item(outside)

    monkeypatch.setattr(document_files, "FILES_ROOT", storage)
    monkeypatch.setattr(files, "get_document", fake_get_document)

    with pytest.raises(HTTPException) as exc_info:
        await files.get_user_document_content(
            "doc-1",
            current_user=_user(),
            session=object(),
            purpose="preview",
        )
    assert exc_info.value.status_code == 404
