from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from multi_domain_enterprise_project.core.audit import append_audit_event
from multi_domain_enterprise_project.core.auth import CurrentUser, require_permissions
from multi_domain_enterprise_project.core.database import get_session
from multi_domain_enterprise_project.core.observability import request_id_var

router = APIRouter(prefix="/evaluation/runs", tags=["enterprise-evaluation"])
REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "evals" / "dataset_registry.json"
Session = Annotated[AsyncSession, Depends(get_session)]
EnterpriseReader = Annotated[CurrentUser, Depends(require_permissions("audit:read", "kb:read"))]


class DatasetSource(BaseModel):
    label: str
    url: str


class DatasetDistribution(BaseModel):
    label: str
    count: int


class RegisteredArtifact(BaseModel):
    path: str
    role: str
    distribution: Literal["repository", "local_cache"]
    expected_size_bytes: int
    expected_sha256: str
    record_count: int | None = None


class RegisteredDataset(BaseModel):
    run_id: str
    name: str
    benchmark_type: str
    sample_count: int
    split: str
    seed: int | None = None
    selection_rule: str
    source_urls: list[DatasetSource]
    distributions: list[DatasetDistribution]
    artifacts: list[RegisteredArtifact]
    leakage_controls: list[str]
    limitations: list[str]


class DatasetRegistry(BaseModel):
    version: int
    datasets: list[RegisteredDataset]


class DatasetArtifact(BaseModel):
    path: str
    role: str
    distribution: Literal["repository", "local_cache"]
    expected_size_bytes: int
    actual_size_bytes: int | None = None
    expected_sha256: str
    actual_sha256: str | None = None
    record_count: int | None = None
    available: bool
    integrity: Literal["verified", "mismatch", "not_distributed", "missing"]


class EvaluationDatasetDetail(BaseModel):
    registry_version: int
    checked_at: str
    run_id: str
    name: str
    benchmark_type: str
    sample_count: int
    split: str
    seed: int | None = None
    selection_rule: str
    source_urls: list[DatasetSource]
    distributions: list[DatasetDistribution]
    artifacts: list[DatasetArtifact]
    leakage_controls: list[str]
    limitations: list[str]
    raw_samples_exposed: bool = False
    registry_note: str = "原始数据缓存不随仓库分发；仓库文本按 LF 规范化摘要，供跨平台完整性核验。"


def _load_registry() -> DatasetRegistry:
    if not REGISTRY_PATH.is_file():
        raise RuntimeError("评测数据集登记清单不存在")
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return DatasetRegistry.model_validate(payload)


def _artifact_bytes(path: Path, distribution: str) -> bytes:
    payload = path.read_bytes()
    if distribution == "repository" and path.suffix.lower() in {".json", ".md", ".py"}:
        return payload.replace(b"\r\n", b"\n")
    return payload


def _inspect_artifact(item: RegisteredArtifact) -> DatasetArtifact:
    path = (REPO_ROOT / item.path).resolve()
    if not path.is_relative_to(REPO_ROOT):
        raise RuntimeError("评测数据集登记路径越界")
    if not path.is_file():
        integrity = "not_distributed" if item.distribution == "local_cache" else "missing"
        return DatasetArtifact(**item.model_dump(), available=False, integrity=integrity)

    physical_size = path.stat().st_size
    validation_payload = _artifact_bytes(path, item.distribution)
    actual_sha256 = hashlib.sha256(validation_payload).hexdigest()
    integrity = (
        "verified"
        if len(validation_payload) == item.expected_size_bytes and actual_sha256 == item.expected_sha256
        else "mismatch"
    )
    return DatasetArtifact(
        **item.model_dump(),
        actual_size_bytes=physical_size,
        actual_sha256=actual_sha256,
        available=True,
        integrity=integrity,
    )


@router.get("/{run_id}/dataset", response_model=EvaluationDatasetDetail)
async def get_evaluation_dataset_detail(
    run_id: str,
    current_user: EnterpriseReader,
    session: Session,
) -> EvaluationDatasetDetail:
    registry = _load_registry()
    item = next((candidate for candidate in registry.datasets if candidate.run_id == run_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="评测数据集登记不存在")

    artifacts = [_inspect_artifact(artifact) for artifact in item.artifacts]
    response = EvaluationDatasetDetail(
        registry_version=registry.version,
        checked_at=datetime.now(UTC).isoformat(),
        **item.model_dump(exclude={"artifacts"}),
        artifacts=artifacts,
    )
    await append_audit_event(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        source="api",
        action="evaluation.dataset_read",
        resource_type="evaluation_dataset",
        resource_id=run_id,
        outcome="success",
        request_id=request_id_var.get(),
        metadata={
            "artifact_count": len(artifacts),
            "verified_count": sum(artifact.integrity == "verified" for artifact in artifacts),
            "mismatch_count": sum(artifact.integrity == "mismatch" for artifact in artifacts),
        },
    )
    return response
