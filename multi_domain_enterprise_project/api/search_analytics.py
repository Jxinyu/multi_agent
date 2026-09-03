from __future__ import annotations

import math
from collections import Counter
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from multi_domain_enterprise_project.core.audit import append_audit_event, list_audit_events
from multi_domain_enterprise_project.core.auth import CurrentUser, require_permissions
from multi_domain_enterprise_project.core.database import get_session
from multi_domain_enterprise_project.core.observability import request_id_var

router = APIRouter(prefix="/search-analytics", tags=["enterprise-search"])
Session = Annotated[AsyncSession, Depends(get_session)]
EnterpriseReader = Annotated[CurrentUser, Depends(require_permissions("audit:read", "kb:read"))]


class DistributionItem(BaseModel):
    id: str
    count: int = Field(ge=0)


class SearchLatencySummary(BaseModel):
    sample_count: int = Field(ge=0)
    average_ms: int | None = Field(default=None, ge=0)
    p50_ms: int | None = Field(default=None, ge=0)
    p95_ms: int | None = Field(default=None, ge=0)
    maximum_ms: int | None = Field(default=None, ge=0)


class SearchResultSummary(BaseModel):
    sample_count: int = Field(ge=0)
    average_count: float | None = Field(default=None, ge=0)
    zero_result_count: int = Field(ge=0)
    zero_result_rate: float | None = Field(default=None, ge=0, le=1)


class SearchAnalyticsEvent(BaseModel):
    id: str
    actor_id: str
    action: Literal["search.completed", "search.failed"]
    outcome: Literal["success", "failure", "denied"]
    occurred_at: str
    request_id: str | None = None
    mode: str | None = None
    elapsed_ms: int | None = Field(default=None, ge=0)
    result_count: int | None = Field(default=None, ge=0)
    error_type: str | None = None


class SearchAnalyticsResponse(BaseModel):
    checked_at: str
    tenant_id: str
    audit_window_size: int = Field(ge=0)
    audit_window_complete: bool
    search_event_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    success_rate: float | None = Field(default=None, ge=0, le=1)
    latency: SearchLatencySummary
    results: SearchResultSummary
    modes: list[DistributionItem]
    error_types: list[DistributionItem]
    recent_events: list[SearchAnalyticsEvent]
    data_window: str = "最近 200 条租户审计事件"
    privacy_note: str = "查询原文及其摘要不返回前端；本页仅展示运行指标和审计标识。"


def _non_negative_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _non_negative_integer(value: Any) -> int | None:
    number = _non_negative_number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _nearest_rank(values: list[float], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index])


def _distribution(values: list[str]) -> list[DistributionItem]:
    counts = Counter(values)
    return [
        DistributionItem(id=item, count=count)
        for item, count in sorted(counts.items(), key=lambda entry: (-entry[1], entry[0]))
    ]


def _safe_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _event_view(event: dict[str, Any]) -> SearchAnalyticsEvent:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    return SearchAnalyticsEvent(
        id=str(event["id"]),
        actor_id=str(event["actor_id"]),
        action=str(event["action"]),
        outcome=str(event["outcome"]),
        occurred_at=str(event["occurred_at"]),
        request_id=_safe_text(event.get("request_id")),
        mode=_safe_text(metadata.get("mode")),
        elapsed_ms=_non_negative_integer(metadata.get("elapsed_ms")),
        result_count=_non_negative_integer(metadata.get("result_count")),
        error_type=_safe_text(metadata.get("error_type")),
    )


@router.get("", response_model=SearchAnalyticsResponse)
async def get_search_analytics(
    current_user: EnterpriseReader,
    session: Session,
) -> SearchAnalyticsResponse:
    events, cursor = await list_audit_events(
        session,
        tenant_id=current_user.tenant_id,
        limit=200,
    )
    search_events = [
        event for event in events if event.get("action") in {"search.completed", "search.failed"}
    ]
    completed = [event for event in search_events if event.get("action") == "search.completed"]
    failed = [event for event in search_events if event.get("action") == "search.failed"]

    latencies = [
        value
        for event in completed
        if (value := _non_negative_number((event.get("metadata") or {}).get("elapsed_ms"))) is not None
    ]
    result_counts = [
        value
        for event in completed
        if (value := _non_negative_integer((event.get("metadata") or {}).get("result_count"))) is not None
    ]
    modes = [
        value
        for event in search_events
        if (value := _safe_text((event.get("metadata") or {}).get("mode"))) is not None
    ]
    error_types = [
        value
        for event in failed
        if (value := _safe_text((event.get("metadata") or {}).get("error_type"))) is not None
    ]
    zero_result_count = result_counts.count(0)
    event_count = len(search_events)
    response = SearchAnalyticsResponse(
        checked_at=datetime.now(UTC).isoformat(),
        tenant_id=current_user.tenant_id,
        audit_window_size=len(events),
        audit_window_complete=cursor is None,
        search_event_count=event_count,
        completed_count=len(completed),
        failed_count=len(failed),
        success_rate=len(completed) / event_count if event_count else None,
        latency=SearchLatencySummary(
            sample_count=len(latencies),
            average_ms=round(sum(latencies) / len(latencies)) if latencies else None,
            p50_ms=_nearest_rank(latencies, 0.50),
            p95_ms=_nearest_rank(latencies, 0.95),
            maximum_ms=round(max(latencies)) if latencies else None,
        ),
        results=SearchResultSummary(
            sample_count=len(result_counts),
            average_count=round(sum(result_counts) / len(result_counts), 2) if result_counts else None,
            zero_result_count=zero_result_count,
            zero_result_rate=zero_result_count / len(result_counts) if result_counts else None,
        ),
        modes=_distribution(modes),
        error_types=_distribution(error_types),
        recent_events=[_event_view(event) for event in search_events[:20]],
    )
    await append_audit_event(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        source="api",
        action="search.analytics_read",
        resource_type="search_analytics",
        resource_id=current_user.tenant_id,
        outcome="success",
        request_id=request_id_var.get(),
        metadata={
            "audit_window_size": len(events),
            "search_event_count": event_count,
            "latency_sample_count": len(latencies),
            "result_sample_count": len(result_counts),
            "window_complete": cursor is None,
        },
    )
    return response
