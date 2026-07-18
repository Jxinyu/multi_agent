from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from config import settings
from multi_domain_enterprise_project.core import auth
from multi_domain_enterprise_project.main import app


@pytest.fixture
def development_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    monkeypatch.setattr(settings.auth, "mode", "development")
    monkeypatch.setattr(settings.auth, "private_key_path", str(private_path))
    monkeypatch.setattr(settings.auth, "public_key_path", str(public_path))
    auth._read_key.cache_clear()
    yield
    auth._read_key.cache_clear()


@pytest.mark.asyncio
async def test_api_rejects_missing_token_and_accepts_valid_token(development_keys: None) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await client.get("/api/auth/me")
        token_response = await client.post("/api/auth/development-token")
        authenticated = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token_response.json()['access_token']}"},
        )

    assert unauthorized.status_code == 401
    assert token_response.status_code == 200
    assert authenticated.status_code == 200
    payload = authenticated.json()["user"]
    assert payload["tenant_id"] == settings.auth.development_tenant_id
    assert "access_token" not in payload


@pytest.mark.asyncio
async def test_tampered_token_is_rejected(development_keys: None) -> None:
    token = auth.create_development_token().access_token
    header, payload, signature = token.split(".")
    signature_chars = list(signature)
    index = len(signature_chars) // 2
    signature_chars[index] = "A" if signature_chars[index] != "A" else "B"
    tampered = ".".join((header, payload, "".join(signature_chars)))
    with pytest.raises(HTTPException) as exc_info:
        await auth.verify_access_token(tampered)
    assert exc_info.value.status_code == 401


def test_openapi_excludes_server_paths_and_marks_protected_routes() -> None:
    schema = app.openapi()
    item_properties = schema["components"]["schemas"]["KnowledgeBaseItem"]["properties"]
    assert "file_path" not in item_properties
    assert "file_path_md" not in item_properties
    assert schema["paths"]["/api/admin/documents"]["get"]["security"]
