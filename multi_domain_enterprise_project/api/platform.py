from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from multi_domain_enterprise_project.core.audit import append_audit_event, list_audit_events
from multi_domain_enterprise_project.core.auth import CurrentUser, require_permissions
from multi_domain_enterprise_project.core.database import get_session, list_documents
from multi_domain_enterprise_project.core.observability import request_id_var
from multi_domain_enterprise_project.healthcheck import CHECK_DEFINITIONS, run_checks

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


class DistributionItem(BaseModel):
    id: str
    count: int


class TenantDocumentActivity(BaseModel):
    id: str
    file_name: str
    owner_id: str
    status: str
    mode: str
    upload_time: str


class TenantDetail(BaseModel):
    usage: TenantUsage
    registry_available: bool = False
    audit_window_complete: bool
    audit_window_size: int
    observed_actor_ids: list[str]
    document_statuses: list[DistributionItem]
    parsing_modes: list[DistributionItem]
    audit_outcomes: list[DistributionItem]
    frequent_actions: list[DistributionItem]
    recent_documents: list[TenantDocumentActivity]
    recent_events: list[dict[str, Any]]
    enforcement_note: str = "当前详情仅覆盖令牌租户；跨租户目录、计费与配额控制面尚未接入。"


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


class ServiceProbeDetail(BaseModel):
    service: ServiceStatus
    checked_at: str
    method: str
    success_condition: str
    operational_role: str
    timeout_seconds: int
    history_available: bool = False
    configuration_source: str = "服务端启动配置（端点与凭据不返回前端）"


class ModelItem(BaseModel):
    name: str
    size_bytes: int | None = None
    modified_at: str | None = None
    roles: list[str] = Field(default_factory=list)
    configured: bool = False
    installed: bool | None = None


class ModelInventory(BaseModel):
    connected: bool
    endpoint: str
    models: list[ModelItem]
    error: str | None = None


class ModelRuntimeDetail(BaseModel):
    name: str
    endpoint: str
    checked_at: str
    roles: list[str] = Field(default_factory=list)
    configured: bool
    runtime_connected: bool
    installed: bool | None = None
    size_bytes: int | None = None
    modified_at: str | None = None
    metadata_available: bool = False
    process_available: bool = False
    running: bool | None = None
    format: str | None = None
    family: str | None = None
    families: list[str] = Field(default_factory=list)
    parameter_size: str | None = None
    quantization_level: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    maximum_context_length: int | None = None
    active_context_length: int | None = None
    loaded_size_bytes: int | None = None
    vram_size_bytes: int | None = None
    expires_at: str | None = None
    issues: list[str] = Field(default_factory=list)
    capacity_metrics_available: bool = False
    capacity_note: str = "Ollama 接口不提供 QPS、请求队列和 GPU 利用率，当前不推算并发容量。"


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


def _distribution(values: list[str], *, limit: int | None = None) -> list[DistributionItem]:
    return [DistributionItem(id=item, count=count) for item, count in Counter(values).most_common(limit)]


def _configured_model_roles() -> dict[str, list[str]]:
    roles: dict[str, list[str]] = {}
    for name, role in (
        (settings.ollama.embedding_model.strip(), "向量嵌入"),
        (settings.ollama.vlm_model.strip(), "视觉解析"),
    ):
        if name:
            roles.setdefault(name, []).append(role)
    return roles


def _public_ollama_endpoint() -> str:
    parsed = urlsplit(settings.ollama.base_url)
    if not parsed.scheme or not parsed.hostname:
        return "服务端配置无效"
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    try:
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError:
        return "服务端配置无效"
    return f"{parsed.scheme}://{host}{port}"


def _runtime_issue(operation: str, exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{operation}返回 HTTP {exc.response.status_code}"
    return f"{operation}不可用（{type(exc).__name__}）"


def _model_item(item: dict[str, Any], roles: dict[str, list[str]]) -> ModelItem | None:
    name = str(item.get("name") or item.get("model") or "").strip()
    if not name:
        return None
    return ModelItem(
        name=name,
        size_bytes=item.get("size") if isinstance(item.get("size"), int) else None,
        modified_at=item.get("modified_at") if isinstance(item.get("modified_at"), str) else None,
        roles=roles.get(name, []),
        configured=name in roles,
        installed=True,
    )


def _model_details(payload: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    model_info = payload.get("model_info") if isinstance(payload.get("model_info"), dict) else {}
    architecture = model_info.get("general.architecture")
    context_length = model_info.get(f"{architecture}.context_length") if isinstance(architecture, str) else None
    return details, context_length if isinstance(context_length, int) else None


def _tenant_usage(tenant_id: str, events: list[dict[str, Any]], documents: list[dict[str, Any]]) -> TenantUsage:
    actors = {str(event["actor_id"]) for event in events}
    healthy = sum(item.get("status") in {"completed", "ready"} for item in documents)
    return TenantUsage(
        tenant_id=tenant_id,
        status="active",
        auth_mode=settings.auth.mode,
        observed_users=len(actors),
        document_count=len(documents),
        healthy_document_count=healthy,
        audit_event_count=len(events),
        request_limit_per_minute=settings.runtime.request_rate_limit_per_minute,
        max_file_size_bytes=settings.upload.max_file_size_bytes,
    )


@router.get("/tenants", response_model=TenantDirectory)
async def get_tenant_directory(current_user: PlatformReader, session: Session) -> TenantDirectory:
    events, _ = await list_audit_events(session, tenant_id=current_user.tenant_id, limit=200)
    documents = await list_documents(session, current_user.tenant_id)
    return TenantDirectory(items=[_tenant_usage(current_user.tenant_id, events, documents)])


@router.get("/tenants/{tenant_id}", response_model=TenantDetail)
async def get_tenant_detail(tenant_id: str, current_user: PlatformReader, session: Session) -> TenantDetail:
    if tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="当前部署目录中不存在该租户")

    events, cursor = await list_audit_events(session, tenant_id=tenant_id, limit=200)
    documents = await list_documents(session, tenant_id)
    response = TenantDetail(
        usage=_tenant_usage(tenant_id, events, documents),
        audit_window_complete=cursor is None,
        audit_window_size=len(events),
        observed_actor_ids=sorted({str(event["actor_id"]) for event in events}),
        document_statuses=_distribution([str(item.get("status") or "unknown") for item in documents]),
        parsing_modes=_distribution([str(item.get("mode") or "unknown") for item in documents]),
        audit_outcomes=_distribution([str(item["outcome"]) for item in events]),
        frequent_actions=_distribution([str(item["action"]) for item in events], limit=8),
        recent_documents=[TenantDocumentActivity(**item) for item in documents[:8]],
        recent_events=events[:12],
    )
    await append_audit_event(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        source="api",
        action="platform.tenant_read",
        resource_type="tenant",
        resource_id=tenant_id,
        outcome="success",
        request_id=request_id_var.get(),
        metadata={"audit_window_size": len(events), "document_count": len(documents)},
    )
    return response


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


@router.get("/runtime/services/{service_name}", response_model=ServiceProbeDetail)
async def get_service_probe_detail(
    service_name: str,
    current_user: PlatformReader,
    session: Session,
) -> ServiceProbeDetail:
    definition = CHECK_DEFINITIONS.get(service_name)
    if definition is None:
        raise HTTPException(status_code=404, detail="未知服务探针")
    results = await run_checks({service_name})
    if not results:
        raise HTTPException(status_code=404, detail="服务探针未注册")
    result = results[0]
    response = ServiceProbeDetail(
        service=ServiceStatus(name=result.name, ok=result.ok, detail=result.detail),
        checked_at=datetime.now(UTC).isoformat(),
        method=definition.method,
        success_condition=definition.success_condition,
        operational_role=definition.operational_role,
        timeout_seconds=definition.timeout_seconds,
    )
    await append_audit_event(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        source="api",
        action="platform.service_probe_read",
        resource_type="service_probe",
        resource_id=service_name,
        outcome="success",
        request_id=request_id_var.get(),
        metadata={"probe_ok": result.ok},
    )
    return response


@router.get("/models", response_model=ModelInventory)
async def get_model_inventory(current_user: PlatformReader) -> ModelInventory:
    endpoint = settings.ollama.base_url.rstrip("/")
    public_endpoint = _public_ollama_endpoint()
    roles = _configured_model_roles()
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            response = await client.get(f"{endpoint}/api/tags")
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        models = [
            ModelItem(name=name, roles=model_roles, configured=True, installed=None)
            for name, model_roles in roles.items()
        ]
        return ModelInventory(
            connected=False,
            endpoint=public_endpoint,
            models=models,
            error=_runtime_issue("模型清单", exc),
        )

    raw_models = payload.get("models", []) if isinstance(payload, dict) else []
    models = [model for item in raw_models if isinstance(item, dict) and (model := _model_item(item, roles))]
    installed_names = {model.name for model in models}
    models.extend(
        ModelItem(name=name, roles=model_roles, configured=True, installed=False)
        for name, model_roles in roles.items()
        if name not in installed_names
    )
    return ModelInventory(connected=True, endpoint=public_endpoint, models=models)


@router.get("/models/detail", response_model=ModelRuntimeDetail)
async def get_model_runtime_detail(
    name: str,
    current_user: PlatformReader,
    session: Session,
) -> ModelRuntimeDetail:
    model_name = name.strip()
    if not model_name or len(model_name) > 200:
        raise HTTPException(status_code=404, detail="模型不存在")

    endpoint = settings.ollama.base_url.rstrip("/")
    roles = _configured_model_roles()
    configured = model_name in roles
    checked_at = datetime.now(UTC).isoformat()
    issues: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            tags_response = await client.get(f"{endpoint}/api/tags")
            tags_response.raise_for_status()
            tags_payload = tags_response.json()
            raw_models = tags_payload.get("models", []) if isinstance(tags_payload, dict) else []
            installed_item = next(
                (
                    item for item in raw_models
                    if isinstance(item, dict) and str(item.get("name") or item.get("model") or "").strip() == model_name
                ),
                None,
            )
            if installed_item is None and not configured:
                raise HTTPException(status_code=404, detail="模型不存在")

            show_payload: dict[str, Any] = {}
            metadata_available = False
            if installed_item is not None:
                try:
                    show_response = await client.post(
                        f"{endpoint}/api/show",
                        json={"model": model_name, "verbose": False},
                    )
                    show_response.raise_for_status()
                    candidate = show_response.json()
                    if isinstance(candidate, dict):
                        show_payload = candidate
                        metadata_available = True
                except Exception as exc:
                    issues.append(_runtime_issue("模型详情", exc))

            running_item: dict[str, Any] | None = None
            process_available = False
            try:
                ps_response = await client.get(f"{endpoint}/api/ps")
                ps_response.raise_for_status()
                ps_payload = ps_response.json()
                running_models = ps_payload.get("models", []) if isinstance(ps_payload, dict) else []
                process_available = True
                running_item = next(
                    (
                        item for item in running_models
                        if isinstance(item, dict)
                        and str(item.get("name") or item.get("model") or "").strip() == model_name
                    ),
                    None,
                )
            except Exception as exc:
                issues.append(_runtime_issue("运行进程清单", exc))
    except HTTPException:
        raise
    except Exception as exc:
        if not configured:
            raise HTTPException(status_code=404, detail="运行时不可用，无法核验该模型") from exc
        response = ModelRuntimeDetail(
            name=model_name,
            endpoint=_public_ollama_endpoint(),
            checked_at=checked_at,
            roles=roles[model_name],
            configured=True,
            runtime_connected=False,
            installed=None,
            issues=[_runtime_issue("模型清单", exc)],
        )
        await append_audit_event(
            session,
            tenant_id=current_user.tenant_id,
            actor_id=current_user.user_id,
            source="api",
            action="platform.model_runtime_read",
            resource_type="model_runtime",
            resource_id=model_name,
            outcome="success",
            request_id=request_id_var.get(),
            metadata={"runtime_connected": False, "installed": None},
        )
        return response

    tag_details = installed_item.get("details") if isinstance(installed_item, dict) else {}
    if not isinstance(tag_details, dict):
        tag_details = {}
    show_details, maximum_context_length = _model_details(show_payload)
    details = show_details or tag_details
    capabilities = show_payload.get("capabilities", [])
    if not isinstance(capabilities, list):
        capabilities = []
    families = details.get("families", [])
    if not isinstance(families, list):
        families = []
    response = ModelRuntimeDetail(
        name=model_name,
        endpoint=_public_ollama_endpoint(),
        checked_at=checked_at,
        roles=roles.get(model_name, []),
        configured=configured,
        runtime_connected=True,
        installed=installed_item is not None,
        size_bytes=installed_item.get("size") if isinstance(installed_item, dict) and isinstance(installed_item.get("size"), int) else None,
        modified_at=installed_item.get("modified_at") if isinstance(installed_item, dict) and isinstance(installed_item.get("modified_at"), str) else None,
        metadata_available=metadata_available,
        process_available=process_available,
        running=running_item is not None if process_available else None,
        format=details.get("format") if isinstance(details.get("format"), str) else None,
        family=details.get("family") if isinstance(details.get("family"), str) else None,
        families=[item for item in families if isinstance(item, str)],
        parameter_size=details.get("parameter_size") if isinstance(details.get("parameter_size"), str) else None,
        quantization_level=details.get("quantization_level") if isinstance(details.get("quantization_level"), str) else None,
        capabilities=[item for item in capabilities if isinstance(item, str)],
        maximum_context_length=maximum_context_length,
        active_context_length=running_item.get("context_length") if running_item and isinstance(running_item.get("context_length"), int) else None,
        loaded_size_bytes=running_item.get("size") if running_item and isinstance(running_item.get("size"), int) else None,
        vram_size_bytes=running_item.get("size_vram") if running_item and isinstance(running_item.get("size_vram"), int) else None,
        expires_at=running_item.get("expires_at") if running_item and isinstance(running_item.get("expires_at"), str) else None,
        issues=issues,
    )
    await append_audit_event(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        source="api",
        action="platform.model_runtime_read",
        resource_type="model_runtime",
        resource_id=model_name,
        outcome="success",
        request_id=request_id_var.get(),
        metadata={"runtime_connected": True, "installed": response.installed, "running": response.running},
    )
    return response


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
