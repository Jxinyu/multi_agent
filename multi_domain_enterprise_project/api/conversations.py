from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from multi_domain_enterprise_project.core.audit import append_audit_event, list_audit_events
from multi_domain_enterprise_project.core.auth import CurrentUser, require_permissions
from multi_domain_enterprise_project.core.database import (
    get_session,
    get_user_conversation,
    list_user_conversations,
    set_conversation_feedback,
)
from multi_domain_enterprise_project.core.observability import request_id_var
from multi_domain_enterprise_project.core.user_views import (
    UserTaskDetailResponse,
    UserTaskFeedbackRequest,
    UserTaskListResponse,
    build_persisted_user_tasks,
    build_user_tasks,
)

router = APIRouter(prefix="/api/tasks", tags=["conversations"])
Session = Annotated[AsyncSession, Depends(get_session)]
ChatUser = Annotated[CurrentUser, Depends(require_permissions("chat:use"))]
TaskId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{8,128}$")]


@router.get("", response_model=UserTaskListResponse)
async def list_tasks(current_user: ChatUser, session: Session) -> UserTaskListResponse:
    events, _ = await list_audit_events(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        limit=200,
    )
    legacy_items = build_user_tasks(events)
    persisted_items = build_persisted_user_tasks(
        await list_user_conversations(
            session,
            tenant_id=current_user.tenant_id,
            owner_id=current_user.user_id,
        )
    )
    merged = {item.id: item for item in legacy_items}
    merged.update({item.id: item for item in persisted_items})
    return UserTaskListResponse(items=sorted(merged.values(), key=lambda item: item.updated_at, reverse=True))


@router.get("/{task_id}", response_model=UserTaskDetailResponse)
async def get_task(task_id: TaskId, current_user: ChatUser, session: Session) -> UserTaskDetailResponse:
    item = await get_user_conversation(
        session,
        thread_id=task_id,
        tenant_id=current_user.tenant_id,
        owner_id=current_user.user_id,
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该历史任务没有可恢复的会话详情")
    return UserTaskDetailResponse(
        id=item["thread_id"],
        status=item["status"],
        title=item["title"],
        created_at=item["created_at"],
        updated_at=item["updated_at"],
        attachment_count=item["attachment_count"],
        waiting_prompt=item["waiting_prompt"],
        feedback=item["feedback"],
        messages=item["messages"],
    )


@router.post("/{task_id}/feedback")
async def set_task_feedback(
    task_id: TaskId,
    request: UserTaskFeedbackRequest,
    current_user: ChatUser,
    session: Session,
) -> dict[str, str | bool]:
    item = await get_user_conversation(
        session,
        thread_id=task_id,
        tenant_id=current_user.tenant_id,
        owner_id=current_user.user_id,
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    saved = await set_conversation_feedback(
        session,
        conversation_id=item["id"],
        user_id=current_user.user_id,
        rating=request.rating,
    )
    if not saved:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前会话尚无可评价的助手答案")
    await append_audit_event(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        source="api",
        action="chat.feedback",
        resource_type="conversation",
        resource_id=task_id,
        outcome="success",
        request_id=request_id_var.get(),
        metadata={"rating": request.rating},
    )
    return {"success": True, "rating": request.rating}
