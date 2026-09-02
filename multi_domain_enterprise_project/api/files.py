from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from multi_domain_enterprise_project.core.audit import append_audit_event
from multi_domain_enterprise_project.core.auth import CurrentUser, require_permissions
from multi_domain_enterprise_project.core.database import get_document, get_session
from multi_domain_enterprise_project.core.document_files import resolve_document_file
from multi_domain_enterprise_project.core.observability import request_id_var
from multi_domain_enterprise_project.rag.authorization import RetrievalAuthorization, is_metadata_authorized

router = APIRouter(prefix="/api", tags=["document-files"])
Session = Annotated[AsyncSession, Depends(get_session)]
KbReader = Annotated[CurrentUser, Depends(require_permissions("kb:read"))]
Purpose = Literal["preview", "download"]


async def _document_file_response(
    document_id: str,
    purpose: Purpose,
    current_user: CurrentUser,
    session: AsyncSession,
    *,
    enforce_acl: bool,
) -> FileResponse:
    item = await get_document(session, document_id, current_user.tenant_id)
    if item is None:
        raise HTTPException(status_code=404, detail="文档不存在或无权访问")
    if enforce_acl:
        scope = RetrievalAuthorization(
            tenant_id=current_user.tenant_id,
            user_id=current_user.user_id,
            acl=tuple(current_user.groups),
        )
        if not is_metadata_authorized(item, scope):
            raise HTTPException(status_code=404, detail="文档不存在或无权访问")
    try:
        path, file_name, media_type, kind = resolve_document_file(item)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="文档原文件不存在") from exc

    await append_audit_event(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        source="api",
        action=f"document.original_{purpose}",
        resource_type="document",
        resource_id=document_id,
        outcome="success",
        request_id=request_id_var.get(),
        metadata={"extension": Path(file_name).suffix.lower(), "file_size": path.stat().st_size},
    )
    disposition = "inline" if purpose == "preview" and kind != "unsupported" else "attachment"
    return FileResponse(
        path,
        media_type=media_type,
        filename=file_name,
        content_disposition_type=disposition,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/documents/{document_id}/content", response_class=FileResponse)
async def get_user_document_content(
    document_id: str,
    current_user: KbReader,
    session: Session,
    purpose: Annotated[Purpose, Query()] = "preview",
) -> FileResponse:
    return await _document_file_response(
        document_id,
        purpose,
        current_user,
        session,
        enforce_acl=True,
    )


@router.get("/admin/documents/{document_id}/content", response_class=FileResponse)
async def get_enterprise_document_content(
    document_id: str,
    current_user: KbReader,
    session: Session,
    purpose: Annotated[Purpose, Query()] = "preview",
) -> FileResponse:
    return await _document_file_response(
        document_id,
        purpose,
        current_user,
        session,
        enforce_acl=False,
    )
