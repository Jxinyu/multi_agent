from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from config import settings

REPO_ROOT = Path(__file__).resolve().parents[2]
bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    user_id: str
    username: str
    tenant_id: str
    role: str
    permissions: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    access_token: str = Field(exclude=True, repr=False)


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


def _configured_path(value: str, setting_name: str) -> Path:
    if not value:
        raise RuntimeError(f"{setting_name} 未配置")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    path = path.resolve()
    if not path.is_file():
        raise RuntimeError(f"{setting_name} 指向的文件不存在: {path}")
    return path


@lru_cache(maxsize=2)
def _read_key(path_value: str, setting_name: str) -> str:
    return _configured_path(path_value, setting_name).read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    if not settings.auth.jwks_url:
        raise RuntimeError("AUTH_JWKS_URL 未配置")
    return jwt.PyJWKClient(settings.auth.jwks_url, cache_keys=True)


async def _verification_key(token: str) -> Any:
    if settings.auth.mode == "oidc":
        signing_key = await asyncio.to_thread(_jwks_client().get_signing_key_from_jwt, token)
        return signing_key.key
    return _read_key(settings.auth.public_key_path, "AUTH_PUBLIC_KEY_PATH")


def _claim_list(claims: dict[str, Any], list_name: str, text_name: str) -> list[str]:
    value = claims.get(list_name)
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    text = claims.get(text_name)
    if isinstance(text, str):
        return [item for item in text.replace("|", " ").split() if item]
    return []


async def verify_access_token(token: str) -> CurrentUser:
    try:
        key = await _verification_key(token)
        claims = jwt.decode(
            token,
            key,
            algorithms=settings.auth.algorithms,
            issuer=settings.auth.issuer,
            audience=settings.auth.audience,
            options={"require": ["exp", "iat", "sub", "tenant_id"]},
        )
    except (jwt.PyJWTError, RuntimeError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="访问令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    permissions = _claim_list(claims, "permissions", "scope")
    groups = _claim_list(claims, "groups", "acl")
    user_id = str(claims["sub"])
    return CurrentUser(
        user_id=user_id,
        username=str(claims.get("preferred_username") or claims.get("username") or user_id),
        tenant_id=str(claims["tenant_id"]),
        role=str(claims.get("role") or "user"),
        permissions=permissions,
        groups=groups,
        access_token=token,
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 Bearer 访问令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await verify_access_token(credentials.credentials)


def require_permissions(*required: str) -> Callable[..., Any]:
    async def dependency(current_user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        missing = [permission for permission in required if permission not in current_user.permissions]
        if missing:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前账号权限不足")
        return current_user

    return dependency


def create_development_token() -> AuthTokenResponse:
    if settings.auth.mode != "development":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=settings.auth.token_ttl_seconds)
    private_key = _read_key(settings.auth.private_key_path, "AUTH_PRIVATE_KEY_PATH")
    claims = {
        "sub": settings.auth.development_user_id,
        "preferred_username": settings.auth.development_username,
        "tenant_id": settings.auth.development_tenant_id,
        "tenant": settings.auth.development_tenant_id,
        "role": settings.auth.development_role,
        "permissions": settings.auth.development_permissions,
        "scope": " ".join(settings.auth.development_permissions),
        "groups": ["private", "tenant"],
        "acl": "private|tenant",
        "iss": settings.auth.issuer,
        "aud": settings.auth.audience,
        "iat": now,
        "exp": expires,
    }
    token = jwt.encode(claims, private_key, algorithm=settings.auth.algorithms[0])
    return AuthTokenResponse(
        access_token=token,
        expires_in=settings.auth.token_ttl_seconds,
    )
