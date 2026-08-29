from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    title: str | None = Field(default=None, max_length=512)
    mode: Literal["milvus", "graph", "mg"] = "mg"


class SearchEvidenceItem(BaseModel):
    id: str
    source: str
    content: str
    score: float | None = None
    kind: str
    backend: str


class SearchResponse(BaseModel):
    items: list[SearchEvidenceItem]
    mode: str
    elapsed_ms: int


class UserTaskItem(BaseModel):
    id: str
    status: Literal["running", "waiting", "completed", "failed", "cancelled"]
    created_at: str
    updated_at: str
    attachment_count: int = 0


class UserTaskListResponse(BaseModel):
    items: list[UserTaskItem]


def build_user_tasks(events: list[dict[str, Any]], *, now: datetime | None = None) -> list[UserTaskItem]:
    grouped: dict[str, dict[str, Any]] = {}
    status_by_action = {
        "chat.requested": "running",
        "chat.waiting_input": "waiting",
        "chat.completed": "completed",
        "chat.failed": "failed",
        "chat.cancelled": "cancelled",
    }
    for event in events:
        action = str(event.get("action") or "")
        task_id = str(event.get("resource_id") or "")
        if not task_id or action not in status_by_action:
            continue
        occurred_at = str(event["occurred_at"])
        attachment_count = int((event.get("metadata") or {}).get("attachment_count") or 0)
        current = grouped.get(task_id)
        if current is None:
            grouped[task_id] = {
                "id": task_id,
                "status": status_by_action[action],
                "created_at": occurred_at,
                "updated_at": occurred_at,
                "attachment_count": attachment_count,
            }
            continue
        current["created_at"] = min(current["created_at"], occurred_at)
        current["attachment_count"] = max(current["attachment_count"], attachment_count)

    stale_before = (now or datetime.now(UTC)) - timedelta(minutes=10)
    for item in grouped.values():
        updated_at = datetime.fromisoformat(item["updated_at"])
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        if item["status"] == "running" and updated_at < stale_before:
            item["status"] = "cancelled"
    return [UserTaskItem(**item) for item in grouped.values()]
