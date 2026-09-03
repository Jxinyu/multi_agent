from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from multi_domain_enterprise_project.core.audit import append_audit_event
from multi_domain_enterprise_project.core.auth import CurrentUser, require_permissions
from multi_domain_enterprise_project.core.database import get_session, list_tenant_conversation_feedback
from multi_domain_enterprise_project.core.observability import request_id_var

router = APIRouter(prefix="/feedback-analytics", tags=["enterprise-feedback"])
Session = Annotated[AsyncSession, Depends(get_session)]
EnterpriseReader = Annotated[CurrentUser, Depends(require_permissions("audit:read", "kb:read"))]


class DistributionItem(BaseModel):
    id: str
    count: int = Field(ge=0)


class FeedbackRecordItem(BaseModel):
    id: str
    conversation_id: str
    thread_id: str
    respondent_id: str
    conversation_status: Literal["running", "waiting", "completed", "failed", "cancelled"]
    rating: Literal["helpful", "not_helpful"]
    created_at: str
    updated_at: str
    conversation_updated_at: str


class FeedbackAnalyticsResponse(BaseModel):
    checked_at: str
    tenant_id: str
    feedback_count: int = Field(ge=0)
    helpful_count: int = Field(ge=0)
    not_helpful_count: int = Field(ge=0)
    helpful_rate: float | None = Field(default=None, ge=0, le=1)
    respondent_count: int = Field(ge=0)
    average_per_respondent: float | None = Field(default=None, ge=0)
    window_complete: bool
    ratings: list[DistributionItem]
    conversation_statuses: list[DistributionItem]
    recent_feedback: list[FeedbackRecordItem]
    data_window: str = "最近 200 条当前反馈记录"
    privacy_note: str = "不返回会话标题、问答正文、附件、引用或消息标识。"
    history_note: str = "本页展示反馈记录当前值；评分修改历史需通过 chat.feedback 审计事件核对。"


def _distribution(values: list[str]) -> list[DistributionItem]:
    counts = Counter(values)
    return [
        DistributionItem(id=item, count=count)
        for item, count in sorted(counts.items(), key=lambda entry: (-entry[1], entry[0]))
    ]


@router.get("", response_model=FeedbackAnalyticsResponse)
async def get_feedback_analytics(
    current_user: EnterpriseReader,
    session: Session,
) -> FeedbackAnalyticsResponse:
    records, window_complete = await list_tenant_conversation_feedback(
        session,
        tenant_id=current_user.tenant_id,
        limit=200,
    )
    helpful_count = sum(record["rating"] == "helpful" for record in records)
    not_helpful_count = sum(record["rating"] == "not_helpful" for record in records)
    feedback_count = len(records)
    respondent_count = len({str(record["respondent_id"]) for record in records})
    response = FeedbackAnalyticsResponse(
        checked_at=datetime.now(UTC).isoformat(),
        tenant_id=current_user.tenant_id,
        feedback_count=feedback_count,
        helpful_count=helpful_count,
        not_helpful_count=not_helpful_count,
        helpful_rate=helpful_count / feedback_count if feedback_count else None,
        respondent_count=respondent_count,
        average_per_respondent=(
            round(feedback_count / respondent_count, 2) if respondent_count else None
        ),
        window_complete=window_complete,
        ratings=_distribution([str(record["rating"]) for record in records]),
        conversation_statuses=_distribution(
            [str(record["conversation_status"]) for record in records]
        ),
        recent_feedback=[FeedbackRecordItem(**record) for record in records],
    )
    await append_audit_event(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        source="api",
        action="feedback.analytics_read",
        resource_type="conversation_feedback",
        resource_id=current_user.tenant_id,
        outcome="success",
        request_id=request_id_var.get(),
        metadata={
            "feedback_count": feedback_count,
            "respondent_count": respondent_count,
            "window_complete": window_complete,
        },
    )
    return response
