from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from config import settings
from multi_domain_enterprise_project.core.storage import (
    decode_attachment,
    normalized_extension,
    validate_file_signature,
)
from multi_domain_enterprise_project.rag.documentParser.parser_route import DocumentParserRouter


class AttachmentPayload(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(max_length=128)
    data_base64: str = Field(min_length=1)


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    thread_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,128}$")
    attachments: list[AttachmentPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_attachment_count(self) -> ChatRequest:
        if len(self.attachments) > settings.upload.max_attachments_per_request:
            raise ValueError("附件数量超过限制")
        return self


async def build_attachment_context(attachments: list[AttachmentPayload]) -> tuple[str, list[str]]:
    if not attachments:
        return "", []
    router = DocumentParserRouter(mode="auto")
    sections: list[str] = []
    names: list[str] = []
    with tempfile.TemporaryDirectory(prefix="rag-upper-attachments-") as temp_dir:
        root = Path(temp_dir)
        for attachment in attachments:
            extension = normalized_extension(attachment.name)
            data = decode_attachment(attachment.data_base64, settings.upload.max_attachment_size_bytes)
            path = root / f"{uuid.uuid4().hex}{extension}"
            path.write_bytes(data)
            validate_file_signature(path, extension)
            parsed = await router.route_and_parse(str(path))
            sections.append(f"### 附件: {Path(attachment.name).name}\n{parsed}")
            names.append(Path(attachment.name).name)
    return "\n\n".join(sections), names
