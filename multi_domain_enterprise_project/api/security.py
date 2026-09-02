from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from multi_domain_enterprise_project.core.audit import (
    append_audit_event,
    get_audit_event,
    list_audit_events,
    list_request_audit_events,
)
from multi_domain_enterprise_project.core.auth import CurrentUser, require_permissions
from multi_domain_enterprise_project.core.database import get_session
from multi_domain_enterprise_project.core.observability import request_id_var

router = APIRouter(prefix="/api/admin/audit-events", tags=["admin-security"])
Session = Annotated[AsyncSession, Depends(get_session)]
AuditReader = Annotated[CurrentUser, Depends(require_permissions("audit:read"))]


class AuditEventView(BaseModel):
    id: str
    tenant_id: str
    actor_id: str
    actor_type: str
    source: str
    action: str
    resource_type: str
    resource_id: str | None = None
    outcome: str
    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    occurred_at: str


class AuditEventDetail(BaseModel):
    item: AuditEventView
    related_events: list[AuditEventView]
    trace_complete: bool


class AuditEventListResponse(BaseModel):
    items: list[AuditEventView]
    next_cursor: str | None = None


@router.get("", response_model=AuditEventListResponse)
async def get_audit_events(
    current_user: AuditReader,
    session: Session,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=512),
    action: str | None = Query(default=None, max_length=128),
    outcome: Literal["success", "failure", "denied"] | None = None,
    actor_id: str | None = Query(default=None, max_length=128),
):
    try:
        items, next_cursor = await list_audit_events(
            session,
            tenant_id=current_user.tenant_id,
            limit=limit,
            cursor=cursor,
            action=action,
            outcome=outcome,
            actor_id=actor_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await append_audit_event(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        source="api",
        action="audit.events_read",
        resource_type="audit_event_collection",
        outcome="success",
        request_id=request_id_var.get(),
        metadata={"result_count": len(items)},
    )
    return AuditEventListResponse(
        items=[AuditEventView(**item) for item in items],
        next_cursor=next_cursor,
    )


@router.get("/{event_id}", response_model=AuditEventDetail)
async def get_audit_event_detail(event_id: str, current_user: AuditReader, session: Session):
    item = await get_audit_event(session, tenant_id=current_user.tenant_id, event_id=event_id)
    if item is None:
        raise HTTPException(status_code=404, detail="审计事件不存在")
    related = [item]
    if item.get("request_id"):
        related = await list_request_audit_events(
            session,
            tenant_id=current_user.tenant_id,
            request_id=str(item["request_id"]),
            limit=50,
        )
    await append_audit_event(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        source="api",
        action="audit.event_read",
        resource_type="audit_event",
        resource_id=event_id,
        outcome="success",
        request_id=request_id_var.get(),
    )
    return AuditEventDetail(
        item=AuditEventView(**item),
        related_events=[AuditEventView(**event) for event in related],
        trace_complete=len(related) < 50,
    )
