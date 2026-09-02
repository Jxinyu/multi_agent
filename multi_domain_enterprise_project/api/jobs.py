from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from multi_domain_enterprise_project.core.auth import CurrentUser, require_permissions
from multi_domain_enterprise_project.core.database import (
    IngestionJobRecord,
    KnowledgeDocumentRecord,
    get_document,
    get_session,
    list_documents,
)
from multi_domain_enterprise_project.rag.authorization import RetrievalAuthorization, is_metadata_authorized

router = APIRouter(prefix="/api/admin/jobs", tags=["document-jobs"])
user_router = APIRouter(prefix="/api/jobs", tags=["user-document-jobs"])
Session = Annotated[AsyncSession, Depends(get_session)]
JobReader = Annotated[CurrentUser, Depends(require_permissions("kb:read"))]
JobStatus = Literal["queued", "processing", "succeeded", "failed"]
JobOperation = Literal["ingest", "delete"]


class JobView(BaseModel):
    id: str
    document_id: str
    file_name: str | None = None
    operation: str
    mode: str
    status: str
    attempts: int
    error: str | None = None
    requested_by: str | None = None
    request_id: str | None = None
    created_at: str
    updated_at: str


class JobListResponse(BaseModel):
    items: list[JobView]
    total: int


def _view(job: IngestionJobRecord, file_name: str | None) -> JobView:
    return JobView(
        id=job.id,
        document_id=job.document_id,
        file_name=file_name,
        operation=job.operation,
        mode=job.mode,
        status=job.status,
        attempts=job.attempts,
        error=job.error,
        requested_by=job.requested_by,
        request_id=job.request_id,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
    )


def _filters(
    tenant_id: str,
    document_id: str | None,
    job_status: JobStatus | None,
    operation: JobOperation | None,
    allowed_document_ids: set[str] | None = None,
):
    values = [IngestionJobRecord.tenant_id == tenant_id]
    if allowed_document_ids is not None:
        values.append(IngestionJobRecord.document_id.in_(allowed_document_ids))
    if document_id:
        values.append(IngestionJobRecord.document_id == document_id)
    if job_status:
        values.append(IngestionJobRecord.status == job_status)
    if operation:
        values.append(IngestionJobRecord.operation == operation)
    return values


def _job_query(filters):
    return (
        select(IngestionJobRecord, KnowledgeDocumentRecord.file_name)
        .outerjoin(
            KnowledgeDocumentRecord,
            and_(
                KnowledgeDocumentRecord.id == IngestionJobRecord.document_id,
                KnowledgeDocumentRecord.tenant_id == IngestionJobRecord.tenant_id,
            ),
        )
        .where(*filters)
    )


async def _list(
    session: AsyncSession,
    filters,
    *,
    limit: int,
    offset: int,
) -> JobListResponse:
    total = await session.scalar(select(func.count()).select_from(IngestionJobRecord).where(*filters))
    rows = (
        await session.execute(
            _job_query(filters)
            .order_by(IngestionJobRecord.created_at.desc(), IngestionJobRecord.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return JobListResponse(items=[_view(job, file_name) for job, file_name in rows], total=int(total or 0))


async def _authorized_document_ids(session: AsyncSession, current_user: CurrentUser) -> set[str]:
    scope = RetrievalAuthorization(
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        acl=tuple(current_user.groups),
    )
    documents = await list_documents(session, current_user.tenant_id)
    return {item["id"] for item in documents if is_metadata_authorized(item, scope)}


@router.get("", response_model=JobListResponse)
async def list_jobs(
    current_user: JobReader,
    session: Session,
    document_id: Annotated[str | None, Query(max_length=64)] = None,
    job_status: Annotated[JobStatus | None, Query(alias="status")] = None,
    operation: JobOperation | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    filters = _filters(current_user.tenant_id, document_id, job_status, operation)
    return await _list(session, filters, limit=limit, offset=offset)


@user_router.get("", response_model=JobListResponse)
async def list_user_jobs(
    current_user: JobReader,
    session: Session,
    document_id: Annotated[str | None, Query(max_length=64)] = None,
    job_status: Annotated[JobStatus | None, Query(alias="status")] = None,
    operation: JobOperation | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    allowed = await _authorized_document_ids(session, current_user)
    if not allowed:
        return JobListResponse(items=[], total=0)
    filters = _filters(current_user.tenant_id, document_id, job_status, operation, allowed)
    return await _list(session, filters, limit=limit, offset=offset)


@router.get("/{job_id}", response_model=JobView)
async def get_job(job_id: str, current_user: JobReader, session: Session):
    filters = [
        IngestionJobRecord.id == job_id,
        IngestionJobRecord.tenant_id == current_user.tenant_id,
    ]
    row = (await session.execute(_job_query(filters))).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return _view(row[0], row[1])


@user_router.get("/{job_id}", response_model=JobView)
async def get_user_job(job_id: str, current_user: JobReader, session: Session):
    job = await get_job(job_id, current_user, session)
    document = await get_document(session, job.document_id, current_user.tenant_id)
    scope = RetrievalAuthorization(
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        acl=tuple(current_user.groups),
    )
    if document is None or not is_metadata_authorized(document, scope):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在或无权访问")
    return job
