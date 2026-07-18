from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any, Literal

from fastmcp import Context, FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from pydantic import Field

from config import settings
from multi_domain_enterprise_project.rag.rag_service import retrieve_service

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[2]


def _public_key() -> str:
    configured = settings.auth.public_key_path
    if not configured:
        raise RuntimeError("AUTH_PUBLIC_KEY_PATH 未配置")
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    path = path.resolve()
    if not path.is_file():
        raise RuntimeError(f"AUTH_PUBLIC_KEY_PATH 指向的文件不存在: {path}")
    return path.read_text(encoding="utf-8")


def build_auth() -> JWTVerifier:
    common: dict[str, Any] = {
        "issuer": settings.auth.issuer,
        "audience": settings.auth.audience,
        "algorithm": settings.auth.algorithms[0],
        "required_scopes": ["kb:read"],
    }
    if settings.auth.mode == "oidc":
        if not settings.auth.jwks_url:
            raise RuntimeError("AUTH_MODE=oidc 时必须配置 AUTH_JWKS_URL")
        return JWTVerifier(jwks_uri=settings.auth.jwks_url, ssrf_safe=True, **common)
    return JWTVerifier(public_key=_public_key(), **common)


def _claims_from_context(ctx: Context) -> dict[str, Any]:
    try:
        claims = ctx.request_context.request.user.access_token.claims
    except (AttributeError, KeyError, TypeError) as exc:
        raise PermissionError("认证上下文缺少访问令牌 claims") from exc
    if not isinstance(claims, dict):
        raise PermissionError("访问令牌 claims 格式无效")
    return claims


def _claim_list(claims: dict[str, Any], list_name: str, text_name: str) -> list[str]:
    value = claims.get(list_name)
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    text = claims.get(text_name)
    if isinstance(text, str):
        return [item for item in text.replace("|", " ").split() if item]
    return []


async def build_mcp_server() -> FastMCP:
    mcp = FastMCP(
        "企业知识库检索服务",
        instructions="提供经过租户与权限过滤的企业知识库检索能力。",
        auth=build_auth(),
    )

    @mcp.tool()
    async def query_document(
        query_str: Annotated[str, Field(min_length=1, max_length=4000, description="检索内容")],
        ctx: Context,
        title: Annotated[str | None, Field(max_length=512, description="可选文档标题精确匹配")] = None,
        mode: Annotated[
            Literal["milvus", "graph", "mg"],
            Field(description="milvus、graph 或双路融合 mg"),
        ] = "milvus",
    ) -> str:
        claims = _claims_from_context(ctx)
        tenant_id = str(claims.get("tenant_id") or "")
        user_id = str(claims.get("sub") or "")
        permissions = _claim_list(claims, "permissions", "scope")
        groups = _claim_list(claims, "groups", "acl")
        if not tenant_id or not user_id or "kb:read" not in permissions:
            raise PermissionError("访问令牌缺少租户、用户或知识库读取权限")

        logger.info("执行知识库检索 tenant=%s user=%s mode=%s", tenant_id, user_id, mode)
        return await retrieve_service(
            query_str=query_str,
            title=title,
            tenant_id=tenant_id,
            user_id=user_id,
            acl_list=groups,
            mode=mode,
        )

    return mcp
