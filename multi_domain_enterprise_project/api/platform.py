from __future__ import annotations

from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from multi_domain_enterprise_project.core.audit import list_audit_events
from multi_domain_enterprise_project.core.auth import CurrentUser, require_permissions
from multi_domain_enterprise_project.core.database import get_session, list_documents
from multi_domain_enterprise_project.healthcheck import run_checks

router = APIRouter(prefix="/api/platform", tags=["platform"])
Session = Annotated[AsyncSession, Depends(get_session)]
PlatformReader = Annotated[CurrentUser, Depends(require_permissions("audit:read", "kb:read"))]


class TenantUsage(BaseModel):
    tenant_id: str
    status: str
    auth_mode: str
    observed_users: int
    document_count: int
    healthy_document_count: int
    audit_event_count: int
    request_limit_per_minute: int
    max_file_size_bytes: int
    vector_storage_quota_bytes: int | None = None
    graph_entity_quota: int | None = None
    monthly_token_quota: int | None = None


class TenantDirectory(BaseModel):
    items: list[TenantUsage]
    registry_available: bool = False
    enforcement_note: str = "当前版本仅执行全局请求与上传限制，尚未配置跨租户配额控制面。"


class ServiceStatus(BaseModel):
    name: str
    ok: bool
    detail: str


class RuntimeStatus(BaseModel):
    environment: str
    service_name: str
    services: list[ServiceStatus]
    worker_max_attempts: int
    worker_block_ms: int
    maintenance_operations_enabled: bool = False


class ModelItem(BaseModel):
    name: str
    size_bytes: int | None = None
    modified_at: str | None = None
    roles: list[str] = Field(default_factory=list)


class ModelInventory(BaseModel):
    connected: bool
    endpoint: str
    models: list[ModelItem]
    error: str | None = None


class PublicSetting(BaseModel):
    key: str
    label: str
    value: str


class SettingGroup(BaseModel):
    id: str
    label: str
    items: list[PublicSetting]


class PlatformSettings(BaseModel):
    groups: list[SettingGroup]
    mutable: bool = False
    source: str = "启动配置与环境变量（只读脱敏视图）"


@router.get("/tenants", response_model=TenantDirectory)
async def get_tenant_directory(current_user: PlatformReader, session: Session) -> TenantDirectory:
    events, _ = await list_audit_events(session, tenant_id=current_user.tenant_id, limit=200)
    documents = await list_documents(session, current_user.tenant_id)
    actors = {str(event["actor_id"]) for event in events}
    healthy = sum(item.get("status") in {"completed", "ready"} for item in documents)
    return TenantDirectory(items=[TenantUsage(
        tenant_id=current_user.tenant_id,
        status="active",
        auth_mode=settings.auth.mode,
        observed_users=len(actors),
        document_count=len(documents),
        healthy_document_count=healthy,
        audit_event_count=len(events),
        request_limit_per_minute=settings.runtime.request_rate_limit_per_minute,
        max_file_size_bytes=settings.upload.max_file_size_bytes,
    )])


@router.get("/runtime", response_model=RuntimeStatus)
async def get_runtime_status(current_user: PlatformReader) -> RuntimeStatus:
    results = await run_checks()
    return RuntimeStatus(
        environment=settings.runtime.environment,
        service_name=settings.runtime.service_name,
        services=[ServiceStatus(name=item.name, ok=item.ok, detail=item.detail) for item in results],
        worker_max_attempts=settings.runtime.worker_max_attempts,
        worker_block_ms=settings.runtime.worker_block_ms,
    )


@router.get("/models", response_model=ModelInventory)
async def get_model_inventory(current_user: PlatformReader) -> ModelInventory:
    endpoint = settings.ollama.base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            response = await client.get(f"{endpoint}/api/tags")
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return ModelInventory(connected=False, endpoint=endpoint, models=[], error=f"{type(exc).__name__}: {exc}")

    models = []
    for item in payload.get("models", []):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        roles = []
        if name == settings.ollama.embedding_model:
            roles.append("向量嵌入")
        if name == settings.ollama.vlm_model:
            roles.append("视觉解析")
        models.append(ModelItem(
            name=name,
            size_bytes=item.get("size") if isinstance(item.get("size"), int) else None,
            modified_at=item.get("modified_at") if isinstance(item.get("modified_at"), str) else None,
            roles=roles,
        ))
    return ModelInventory(connected=True, endpoint=endpoint, models=models)


def _setting(key: str, label: str, value: Any) -> PublicSetting:
    if isinstance(value, list):
        rendered = "、".join(str(item) for item in value) or "未配置"
    elif isinstance(value, bool):
        rendered = "启用" if value else "停用"
    else:
        rendered = str(value) if value not in {None, ""} else "未配置"
    return PublicSetting(key=key, label=label, value=rendered)


@router.get("/settings", response_model=PlatformSettings)
async def get_platform_settings(current_user: PlatformReader) -> PlatformSettings:
    return PlatformSettings(groups=[
        SettingGroup(id="runtime", label="运行策略", items=[
            _setting("environment", "运行环境", settings.runtime.environment),
            _setting("request_rate_limit_per_minute", "每分钟请求限制", settings.runtime.request_rate_limit_per_minute),
            _setting("worker_max_attempts", "任务最大尝试次数", settings.runtime.worker_max_attempts),
            _setting("cors_origins", "跨域来源", settings.runtime.cors_origins),
        ]),
        SettingGroup(id="retrieval", label="检索策略", items=[
            _setting("candidate_top_k", "候选 Top K", settings.retrieval.candidate_top_k),
            _setting("reranker_top_n", "重排保留数", settings.reranker.top_n),
            _setting("timeout_seconds", "检索超时（秒）", settings.retrieval.timeout_seconds),
            _setting("max_context_chars", "最大上下文字符", settings.retrieval.max_context_chars),
        ]),
        SettingGroup(id="documents", label="文档策略", items=[
            _setting("max_file_size_bytes", "单文件上限（字节）", settings.upload.max_file_size_bytes),
            _setting("max_files_per_request", "单次文件数", settings.upload.max_files_per_request),
            _setting("allowed_extensions", "允许扩展名", settings.upload.allowed_extensions),
            _setting("llama_parse_tier", "云解析等级", settings.llama_parser.tier),
        ]),
        SettingGroup(id="identity", label="身份与令牌", items=[
            _setting("auth_mode", "认证模式", settings.auth.mode),
            _setting("issuer", "令牌签发方", settings.auth.issuer),
            _setting("audience", "令牌受众", settings.auth.audience),
            _setting("token_ttl_seconds", "令牌有效期（秒）", settings.auth.token_ttl_seconds),
        ]),
    ])
