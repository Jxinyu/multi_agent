from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi import HTTPException

from multi_domain_enterprise_project.api import evaluation_datasets
from multi_domain_enterprise_project.core.auth import CurrentUser


def _enterprise_admin() -> CurrentUser:
    return CurrentUser(
        user_id="enterprise-admin",
        username="admin",
        tenant_id="tenant-a",
        role="admin",
        permissions=["audit:read", "kb:read"],
        groups=["enterprise"],
        access_token="token",
    )


@pytest.mark.asyncio
async def test_dataset_registry_exposes_provenance_without_raw_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audits: list[dict] = []

    async def fake_append(session, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(evaluation_datasets, "append_audit_event", fake_append)
    registry = evaluation_datasets._load_registry()

    assert registry.version == 1
    assert len(registry.datasets) == 4
    for registered in registry.datasets:
        response = await evaluation_datasets.get_evaluation_dataset_detail(
            registered.run_id,
            _enterprise_admin(),
            object(),
        )
        repository_artifacts = [item for item in response.artifacts if item.distribution == "repository"]
        local_artifacts = [item for item in response.artifacts if item.distribution == "local_cache"]

        assert response.raw_samples_exposed is False
        assert response.sample_count > 0
        assert repository_artifacts
        assert all(item.integrity == "verified" for item in repository_artifacts)
        assert all(item.integrity in {"verified", "not_distributed"} for item in local_artifacts)
        assert all(not Path(item.path).is_absolute() for item in response.artifacts)

    assert len(audits) == 4
    assert all(item["action"] == "evaluation.dataset_read" for item in audits)


@pytest.mark.asyncio
async def test_dataset_registry_rejects_unknown_run() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await evaluation_datasets.get_evaluation_dataset_detail(
            "unknown-run",
            _enterprise_admin(),
            object(),
        )
    assert exc_info.value.status_code == 404


def test_dataset_artifact_path_cannot_escape_repository() -> None:
    artifact = evaluation_datasets.RegisteredArtifact(
        path="../outside.json",
        role="非法路径",
        distribution="local_cache",
        expected_size_bytes=1,
        expected_sha256="0" * 64,
    )
    with pytest.raises(RuntimeError, match="路径越界"):
        evaluation_datasets._inspect_artifact(artifact)


def test_dataset_artifact_integrity_is_cross_platform_and_observable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    content = b"first\nsecond\n"
    tracked = tmp_path / "tracked.json"
    tracked.write_bytes(content.replace(b"\n", b"\r\n"))
    monkeypatch.setattr(evaluation_datasets, "REPO_ROOT", tmp_path)
    artifact = evaluation_datasets.RegisteredArtifact(
        path="tracked.json",
        role="测试产物",
        distribution="repository",
        expected_size_bytes=len(content),
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )

    verified = evaluation_datasets._inspect_artifact(artifact)
    mismatched = evaluation_datasets._inspect_artifact(
        artifact.model_copy(update={"expected_sha256": "0" * 64}),
    )
    missing = evaluation_datasets._inspect_artifact(
        artifact.model_copy(update={"path": "raw-cache.json", "distribution": "local_cache"}),
    )

    assert verified.integrity == "verified"
    assert verified.actual_size_bytes == len(content) + 2
    assert mismatched.integrity == "mismatch"
    assert missing.integrity == "not_distributed"
