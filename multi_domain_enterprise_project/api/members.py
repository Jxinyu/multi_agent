from __future__ import annotations

from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from multi_domain_enterprise_project.core.audit import list_audit_events
from multi_domain_enterprise_project.core.auth import CurrentUser, require_permissions
from multi_domain_enterprise_project.core.database import get_session

router = APIRouter(prefix="/api/enterprise/members", tags=["enterprise-members"])
Session = Annotated[AsyncSession, Depends(get_session)]
MemberReader = Annotated[CurrentUser, Depends(require_permissions("audit:read", "kb:read"))]


class ActivityCount(BaseModel):
    id: str
    count: int


class ObservedMemberDetail(BaseModel):
    actor_id: str
    actor_type: str
    identity_source: str
    is_current_user: bool
    role: str | None = None
    permissions: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    event_count: int
    window_complete: bool
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    outcomes: list[ActivityCount]
    actions: list[ActivityCount]
    resource_types: list[ActivityCount]
    recent_events: list[dict[str, Any]]
    directory_managed: bool = False


def _counts(values: list[str], limit: int | None = None) -> list[ActivityCount]:
    items = Counter(values).most_common(limit)
    return [ActivityCount(id=item, count=count) for item, count in items]


@router.get("/{actor_id}", response_model=ObservedMemberDetail)
async def get_observed_member(actor_id: str, current_user: MemberReader, session: Session):
    events, cursor = await list_audit_events(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=actor_id,
        limit=200,
    )
    is_current = actor_id == current_user.user_id
    if not events and not is_current:
        raise HTTPException(status_code=404, detail="当前租户未观测到该身份")

    event_times = [str(item["occurred_at"]) for item in events]
    actor_type = str(events[0].get("actor_type") or "user") if events else "user"
    return ObservedMemberDetail(
        actor_id=actor_id,
        actor_type=actor_type,
        identity_source="当前 JWT" if is_current else "租户审计事件",
        is_current_user=is_current,
        role=current_user.role if is_current else None,
        permissions=current_user.permissions if is_current else [],
        groups=current_user.groups if is_current else [],
        event_count=len(events),
        window_complete=cursor is None,
        first_seen_at=min(event_times) if event_times else None,
        last_seen_at=max(event_times) if event_times else None,
        outcomes=_counts([str(item["outcome"]) for item in events]),
        actions=_counts([str(item["action"]) for item in events], limit=8),
        resource_types=_counts([str(item["resource_type"]) for item in events], limit=8),
        recent_events=events[:12],
    )
