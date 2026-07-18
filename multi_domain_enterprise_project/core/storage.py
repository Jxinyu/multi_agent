from __future__ import annotations

import base64
import binascii
import hashlib
import re
import shutil
import zipfile
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from config import settings

REPO_ROOT = Path(__file__).resolve().parents[2]
KB_ROOT = REPO_ROOT / "data" / "knowledge_base"
FILES_ROOT = KB_ROOT / "files"
PARSED_ROOT = KB_ROOT / "parsed"
UPLOAD_SESSIONS_ROOT = KB_ROOT / "upload_sessions"
UPLOAD_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
STREAM_CHUNK_SIZE = 1024 * 1024


def ensure_storage_roots() -> None:
    FILES_ROOT.mkdir(parents=True, exist_ok=True)
    PARSED_ROOT.mkdir(parents=True, exist_ok=True)
    UPLOAD_SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)


def normalized_extension(file_name: str) -> str:
    extension = Path(Path(file_name).name).suffix.lower()
    if extension not in settings.upload.allowed_extensions:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="不支持的文件类型")
    return extension


def document_path(document_id: str, file_name: str) -> Path:
    ensure_storage_roots()
    return FILES_ROOT / f"{document_id}{normalized_extension(file_name)}"


def parsed_document_path(tenant_id: str, document_id: str) -> Path:
    tenant_key = hashlib.sha256(tenant_id.encode()).hexdigest()[:16]
    if not re.fullmatch(r"[a-f0-9]{32,64}", document_id):
        raise ValueError("非法 document_id")
    ensure_storage_roots()
    return PARSED_ROOT / f"{tenant_key}-{document_id}.md"


def upload_session_dir(upload_id: str) -> Path:
    if not UPLOAD_ID_PATTERN.fullmatch(upload_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="非法 upload_id")
    ensure_storage_roots()
    return UPLOAD_SESSIONS_ROOT / upload_id


async def stream_upload(
    upload: UploadFile,
    target: Path,
    *,
    max_bytes: int,
    expected_bytes: int | None = None,
) -> tuple[int, str]:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".uploading")
    digest = hashlib.sha256()
    total = 0
    try:
        with temporary.open("wb") as output:
            while data := await upload.read(STREAM_CHUNK_SIZE):
                total += len(data)
                if total > max_bytes:
                    raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="文件超过大小限制")
                digest.update(data)
                output.write(data)
        if expected_bytes is not None and total != expected_bytes:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="分片大小与声明不一致")
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return total, digest.hexdigest()


def validate_file_signature(path: Path, extension: str) -> None:
    with path.open("rb") as source:
        header = source.read(16)
    valid = True
    if extension == ".pdf":
        valid = header.startswith(b"%PDF-")
    elif extension == ".png":
        valid = header.startswith(b"\x89PNG\r\n\x1a\n")
    elif extension in {".jpg", ".jpeg"}:
        valid = header.startswith(b"\xff\xd8\xff")
    elif extension == ".bmp":
        valid = header.startswith(b"BM")
    elif extension in {".docx", ".pptx", ".xlsx"}:
        expected_root = {".docx": "word/", ".pptx": "ppt/", ".xlsx": "xl/"}[extension]
        try:
            with zipfile.ZipFile(path) as archive:
                valid = any(name.startswith(expected_root) for name in archive.namelist())
        except zipfile.BadZipFile:
            valid = False
    if not valid:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="文件内容与扩展名不匹配")


def decode_attachment(value: str, max_bytes: int) -> bytes:
    if value.startswith("data:") and "," in value:
        value = value.split(",", 1)[1]
    estimated = len(value) * 3 // 4
    if estimated > max_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="附件超过大小限制")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="附件 Base64 数据无效") from exc
    if len(decoded) > max_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="附件超过大小限制")
    return decoded


def combine_chunks(upload_id: str, expected_chunks: int, target: Path, expected_size: int) -> str:
    chunks_dir = upload_session_dir(upload_id) / "chunks"
    digest = hashlib.sha256()
    total = 0
    temporary = target.with_suffix(target.suffix + ".assembling")
    try:
        with temporary.open("wb") as output:
            for index in range(expected_chunks):
                chunk_path = chunks_dir / f"{index}.part"
                if not chunk_path.is_file():
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="分片未上传完整")
                with chunk_path.open("rb") as source:
                    while data := source.read(STREAM_CHUNK_SIZE):
                        total += len(data)
                        if total > expected_size:
                            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="实际文件大于声明大小")
                        digest.update(data)
                        output.write(data)
        if total != expected_size:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="实际文件大小与声明不一致")
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return digest.hexdigest()


def remove_storage_path(path_value: str | None) -> None:
    if not path_value:
        return
    path = Path(path_value).resolve()
    root = KB_ROOT.resolve()
    if not path.is_relative_to(root):
        raise ValueError("拒绝删除知识库目录之外的文件")
    path.unlink(missing_ok=True)


def remove_upload_session_files(upload_id: str) -> None:
    directory = upload_session_dir(upload_id).resolve()
    if not directory.is_relative_to(UPLOAD_SESSIONS_ROOT.resolve()):
        raise ValueError("拒绝删除上传会话目录之外的路径")
    shutil.rmtree(directory, ignore_errors=False)
