from __future__ import annotations

import pytest

from multi_domain_enterprise_project.api import knowledge_runtime
from multi_domain_enterprise_project.core.auth import CurrentUser


def _reader() -> CurrentUser:
    return CurrentUser(
        user_id="admin-1",
        username="admin",
        tenant_id="tenant-1",
        role="admin",
        permissions=["audit:read", "kb:read"],
        groups=["tenant"],
        access_token="token",
    )


def _document(
    document_id: str,
    *,
    chunks: int,
    backends: dict[str, str],
    status: str = "ready",
) -> dict[str, object]:
    return {
        "id": document_id,
        "file_name": f"{document_id}.pdf",
        "status": status,
        "mode": "hybrid",
        "chunk_count": chunks,
        "backend_status": backends,
    }


@pytest.mark.asyncio
async def test_runtime_compares_only_current_tenant_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_documents(session, tenant_id):
        captured["document_tenant"] = tenant_id
        return [
            _document("ok", chunks=3, backends={"milvus": "success", "neo4j": "success"}),
            _document("bad", chunks=4, backends={"milvus": "success"}),
            _document("queued", chunks=0, backends={}, status="queued"),
        ]

    async def fake_milvus(tenant_id):
        captured["milvus_tenant"] = tenant_id
        return knowledge_runtime.MilvusIndexSnapshot(
            available=True,
            collection_name="company_knowledge_base",
            collection_exists=True,
            indexed_chunks=5,
            indexed_documents=2,
            embedding_dimensions=2560,
            sparse_search_enabled=True,
            scan_complete=True,
            document_chunks={"ok": 3, "bad": 2, "orphan": 1},
        )

    async def fake_neo4j(tenant_id):
        captured["neo4j_tenant"] = tenant_id
        return knowledge_runtime.Neo4jIndexSnapshot(
            available=True,
            indexed_chunks=3,
            indexed_documents=1,
            entity_count=8,
            relationship_count=6,
            scan_complete=True,
            document_chunks={"ok": 3},
        )

    async def fake_audit(session, **kwargs):
        captured["audit"] = kwargs

    monkeypatch.setattr(knowledge_runtime, "list_documents", fake_documents)
    monkeypatch.setattr(knowledge_runtime, "_read_milvus_snapshot", fake_milvus)
    monkeypatch.setattr(knowledge_runtime, "_read_neo4j_snapshot", fake_neo4j)
    monkeypatch.setattr(knowledge_runtime, "append_audit_event", fake_audit)

    response = await knowledge_runtime.get_knowledge_index_runtime(_reader(), object())

    assert captured["document_tenant"] == "tenant-1"
    assert captured["milvus_tenant"] == "tenant-1"
    assert captured["neo4j_tenant"] == "tenant-1"
    assert response.document_count == 3
    assert response.expected_vector_chunks == 7
    assert response.expected_graph_chunks == 3
    assert response.state_counts == {"consistent": 1, "mismatch": 2, "pending": 1}
    assert response.orphan_document_count == 1
    assert response.document_checks[0].document_id == "bad"
    assert response.document_checks[0].issue == "Milvus 为 2 个切片，元数据期望 4 个"
    orphan = next(item for item in response.document_checks if item.document_id == "orphan")
    assert orphan.vector_chunks == 1
    assert orphan.issue == "Milvus 中存在记录，但租户文档表没有对应文档"
    assert captured["audit"]["metadata"]["mismatch_count"] == 2


@pytest.mark.asyncio
async def test_runtime_marks_required_unavailable_backend_as_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_documents(session, tenant_id):
        return [_document("graph-doc", chunks=2, backends={"neo4j": "success"})]

    async def fake_milvus(tenant_id):
        return knowledge_runtime.MilvusIndexSnapshot(
            available=True,
            collection_name="company_knowledge_base",
            collection_exists=True,
            indexed_chunks=0,
            indexed_documents=0,
            scan_complete=True,
        )

    async def fake_neo4j(tenant_id):
        return knowledge_runtime.Neo4jIndexSnapshot(
            available=False,
            error="Neo4j 探针失败（ServiceUnavailable）",
        )

    async def fake_audit(session, **kwargs):
        return None

    monkeypatch.setattr(knowledge_runtime, "list_documents", fake_documents)
    monkeypatch.setattr(knowledge_runtime, "_read_milvus_snapshot", fake_milvus)
    monkeypatch.setattr(knowledge_runtime, "_read_neo4j_snapshot", fake_neo4j)
    monkeypatch.setattr(knowledge_runtime, "append_audit_event", fake_audit)

    response = await knowledge_runtime.get_knowledge_index_runtime(_reader(), object())

    assert response.state_counts == {"unknown": 1}
    assert response.document_checks[0].graph_chunks is None
    assert response.document_checks[0].issue == "后端不可用或文档扫描未完成"
