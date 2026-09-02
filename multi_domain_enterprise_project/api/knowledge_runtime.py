from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from multi_domain_enterprise_project.core.audit import append_audit_event
from multi_domain_enterprise_project.core.auth import CurrentUser, require_permissions
from multi_domain_enterprise_project.core.database import get_session, list_documents
from multi_domain_enterprise_project.core.observability import request_id_var
from multi_domain_enterprise_project.rag.milvus.ingestion_milvus import DEFAULT_COLLECTION_NAME

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/enterprise/knowledge/runtime", tags=["enterprise-knowledge"])
Session = Annotated[AsyncSession, Depends(get_session)]
KnowledgeReader = Annotated[CurrentUser, Depends(require_permissions("kb:read", "audit:read"))]
INDEX_SCAN_LIMIT = 10_000
DOCUMENT_CHECK_LIMIT = 100


class MilvusIndexSnapshot(BaseModel):
    available: bool
    collection_name: str
    collection_exists: bool
    indexed_chunks: int | None = None
    indexed_documents: int | None = None
    embedding_dimensions: int | None = None
    sparse_search_enabled: bool | None = None
    scan_complete: bool = False
    error: str | None = None
    document_chunks: dict[str, int] = Field(default_factory=dict, exclude=True)


class Neo4jIndexSnapshot(BaseModel):
    available: bool
    indexed_chunks: int | None = None
    indexed_documents: int | None = None
    entity_count: int | None = None
    relationship_count: int | None = None
    scan_complete: bool = False
    error: str | None = None
    document_chunks: dict[str, int] = Field(default_factory=dict, exclude=True)


class DocumentIndexCheck(BaseModel):
    document_id: str
    file_name: str
    status: str
    mode: str
    expected_chunks: int
    vector_chunks: int | None
    graph_chunks: int | None
    vector_expected: bool
    graph_expected: bool
    state: Literal["consistent", "mismatch", "pending", "unknown"]
    issue: str | None = None


class KnowledgeIndexRuntime(BaseModel):
    checked_at: str
    tenant_id: str
    document_count: int
    ready_document_count: int
    expected_vector_chunks: int
    expected_graph_chunks: int
    orphan_document_count: int
    milvus: MilvusIndexSnapshot
    neo4j: Neo4jIndexSnapshot
    state_counts: dict[str, int]
    document_checks: list[DocumentIndexCheck]
    document_checks_complete: bool
    observation_note: str


def _tenant_filter(tenant_id: str) -> str:
    return f"tenant_id == {json.dumps(tenant_id, ensure_ascii=False)}"


def _probe_milvus(tenant_id: str) -> MilvusIndexSnapshot:
    from pymilvus import MilvusClient

    client = MilvusClient(uri=settings.milvus.uri)
    try:
        if DEFAULT_COLLECTION_NAME not in client.list_collections():
            return MilvusIndexSnapshot(
                available=True,
                collection_name=DEFAULT_COLLECTION_NAME,
                collection_exists=False,
                indexed_chunks=0,
                indexed_documents=0,
                scan_complete=True,
            )

        description = client.describe_collection(DEFAULT_COLLECTION_NAME)
        count_rows = client.query(
            collection_name=DEFAULT_COLLECTION_NAME,
            filter=_tenant_filter(tenant_id),
            output_fields=["count(*)"],
            timeout=5,
        )
        indexed_chunks = int(count_rows[0].get("count(*)", 0)) if count_rows else 0
        rows = client.query(
            collection_name=DEFAULT_COLLECTION_NAME,
            filter=_tenant_filter(tenant_id),
            output_fields=["document_id"],
            limit=INDEX_SCAN_LIMIT + 1,
            timeout=5,
        )
        scan_complete = len(rows) <= INDEX_SCAN_LIMIT
        document_chunks = Counter(
            str(item["document_id"])
            for item in rows[:INDEX_SCAN_LIMIT]
            if item.get("document_id")
        )
        embedding_field = next(
            (item for item in description.get("fields", []) if item.get("name") == "embedding"),
            {},
        )
        return MilvusIndexSnapshot(
            available=True,
            collection_name=DEFAULT_COLLECTION_NAME,
            collection_exists=True,
            indexed_chunks=indexed_chunks,
            indexed_documents=len(document_chunks) if scan_complete else None,
            embedding_dimensions=embedding_field.get("params", {}).get("dim"),
            sparse_search_enabled=bool(description.get("functions")),
            scan_complete=scan_complete,
            document_chunks=dict(document_chunks) if scan_complete else {},
        )
    finally:
        client.close()


def _probe_neo4j(tenant_id: str) -> Neo4jIndexSnapshot:
    from neo4j import GraphDatabase

    if not settings.neo4j.password:
        return Neo4jIndexSnapshot(available=False, error="Neo4j 凭据未配置")

    driver = GraphDatabase.driver(
        settings.neo4j.url,
        auth=(settings.neo4j.username, settings.neo4j.password),
        connection_timeout=3,
    )
    try:
        driver.verify_connectivity()
        with driver.session() as session:
            summary = session.run(
                """
                MATCH (n)
                WHERE n.tenant_id = $tenant_id
                RETURN count(n) AS node_count,
                       count(CASE WHEN n:Chunk THEN 1 END) AS chunk_count,
                       count(CASE WHEN n:`__Entity__` THEN 1 END) AS entity_count,
                       count(DISTINCT CASE WHEN n:Chunk THEN n.document_id END) AS document_count
                """,
                tenant_id=tenant_id,
            ).single(strict=True)
            relationships = session.run(
                "MATCH ()-[r]->() WHERE r.tenant_id = $tenant_id RETURN count(r) AS count",
                tenant_id=tenant_id,
            ).single(strict=True)
            rows = session.run(
                """
                MATCH (n:Chunk)
                WHERE n.tenant_id = $tenant_id AND n.document_id IS NOT NULL
                RETURN toString(n.document_id) AS document_id, count(n) AS chunks
                ORDER BY document_id
                LIMIT $limit
                """,
                tenant_id=tenant_id,
                limit=INDEX_SCAN_LIMIT + 1,
            ).data()
        scan_complete = len(rows) <= INDEX_SCAN_LIMIT
        return Neo4jIndexSnapshot(
            available=True,
            indexed_chunks=int(summary["chunk_count"]),
            indexed_documents=int(summary["document_count"]),
            entity_count=int(summary["entity_count"]),
            relationship_count=int(relationships["count"]),
            scan_complete=scan_complete,
            document_chunks={
                str(item["document_id"]): int(item["chunks"])
                for item in rows[:INDEX_SCAN_LIMIT]
            } if scan_complete else {},
        )
    finally:
        driver.close()


async def _read_milvus_snapshot(tenant_id: str) -> MilvusIndexSnapshot:
    try:
        return await asyncio.wait_for(asyncio.to_thread(_probe_milvus, tenant_id), timeout=7)
    except Exception as exc:
        logger.exception("Milvus 租户索引探针失败")
        return MilvusIndexSnapshot(
            available=False,
            collection_name=DEFAULT_COLLECTION_NAME,
            collection_exists=False,
            error=f"Milvus 探针失败（{type(exc).__name__}）",
        )


async def _read_neo4j_snapshot(tenant_id: str) -> Neo4jIndexSnapshot:
    try:
        return await asyncio.wait_for(asyncio.to_thread(_probe_neo4j, tenant_id), timeout=7)
    except Exception as exc:
        logger.exception("Neo4j 租户索引探针失败")
        return Neo4jIndexSnapshot(
            available=False,
            error=f"Neo4j 探针失败（{type(exc).__name__}）",
        )


def _successful_backend(document: dict[str, Any], backend: str) -> bool:
    return document.get("backend_status", {}).get(backend) == "success"


def _actual_chunks(snapshot: MilvusIndexSnapshot | Neo4jIndexSnapshot, document_id: str) -> int | None:
    if not snapshot.available or not snapshot.scan_complete:
        return None
    return snapshot.document_chunks.get(document_id, 0)


def _document_check(
    document: dict[str, Any],
    milvus: MilvusIndexSnapshot,
    neo4j: Neo4jIndexSnapshot,
) -> DocumentIndexCheck:
    document_id = str(document["id"])
    status = str(document.get("status") or "unknown")
    expected_chunks = int(document.get("chunk_count") or 0)
    vector_expected = _successful_backend(document, "milvus")
    graph_expected = _successful_backend(document, "neo4j")
    vector_chunks = _actual_chunks(milvus, document_id)
    graph_chunks = _actual_chunks(neo4j, document_id)

    state: Literal["consistent", "mismatch", "pending", "unknown"] = "consistent"
    issue = None
    if status not in {"ready", "completed"}:
        state, issue = "pending", "文档尚未处于可检索终态"
    elif expected_chunks <= 0:
        state, issue = "mismatch", "就绪文档没有记录切片数量"
    elif not vector_expected and not graph_expected:
        state, issue = "mismatch", "就绪文档没有成功后端记录"
    elif (vector_expected and vector_chunks is None) or (graph_expected and graph_chunks is None):
        state, issue = "unknown", "后端不可用或文档扫描未完成"
    elif vector_expected and vector_chunks != expected_chunks:
        state, issue = "mismatch", f"Milvus 为 {vector_chunks} 个切片，元数据期望 {expected_chunks} 个"
    elif graph_expected and graph_chunks != expected_chunks:
        state, issue = "mismatch", f"Neo4j 为 {graph_chunks} 个切片，元数据期望 {expected_chunks} 个"
    elif not vector_expected and vector_chunks:
        state, issue = "mismatch", "Milvus 存在未在元数据中登记的切片"
    elif not graph_expected and graph_chunks:
        state, issue = "mismatch", "Neo4j 存在未在元数据中登记的切片"

    return DocumentIndexCheck(
        document_id=document_id,
        file_name=str(document.get("file_name") or document_id),
        status=status,
        mode=str(document.get("mode") or "unknown"),
        expected_chunks=expected_chunks,
        vector_chunks=vector_chunks,
        graph_chunks=graph_chunks,
        vector_expected=vector_expected,
        graph_expected=graph_expected,
        state=state,
        issue=issue,
    )


def _orphan_check(
    document_id: str,
    milvus: MilvusIndexSnapshot,
    neo4j: Neo4jIndexSnapshot,
) -> DocumentIndexCheck:
    vector_chunks = milvus.document_chunks.get(document_id, 0)
    graph_chunks = neo4j.document_chunks.get(document_id, 0)
    backends = []
    if vector_chunks:
        backends.append("Milvus")
    if graph_chunks:
        backends.append("Neo4j")
    return DocumentIndexCheck(
        document_id=document_id,
        file_name=f"索引记录 {document_id}",
        status="orphaned",
        mode="unknown",
        expected_chunks=0,
        vector_chunks=vector_chunks,
        graph_chunks=graph_chunks,
        vector_expected=False,
        graph_expected=False,
        state="mismatch",
        issue=f"{'、'.join(backends)} 中存在记录，但租户文档表没有对应文档",
    )


@router.get("", response_model=KnowledgeIndexRuntime)
async def get_knowledge_index_runtime(
    current_user: KnowledgeReader,
    session: Session,
) -> KnowledgeIndexRuntime:
    documents = await list_documents(session, current_user.tenant_id)
    milvus, neo4j = await asyncio.gather(
        _read_milvus_snapshot(current_user.tenant_id),
        _read_neo4j_snapshot(current_user.tenant_id),
    )
    checks = [_document_check(item, milvus, neo4j) for item in documents]
    database_document_ids = {str(item["id"]) for item in documents}
    indexed_document_ids = set(milvus.document_chunks).union(neo4j.document_chunks)
    orphan_ids = sorted(indexed_document_ids.difference(database_document_ids))
    checks.extend(_orphan_check(document_id, milvus, neo4j) for document_id in orphan_ids)
    priority = {"mismatch": 0, "unknown": 1, "pending": 2, "consistent": 3}
    checks.sort(key=lambda item: (priority[item.state], item.file_name.casefold()))
    state_counts = Counter(item.state for item in checks)
    response = KnowledgeIndexRuntime(
        checked_at=datetime.now(UTC).isoformat(),
        tenant_id=current_user.tenant_id,
        document_count=len(documents),
        ready_document_count=sum(item.get("status") in {"ready", "completed"} for item in documents),
        expected_vector_chunks=sum(
            int(item.get("chunk_count") or 0) for item in documents if _successful_backend(item, "milvus")
        ),
        expected_graph_chunks=sum(
            int(item.get("chunk_count") or 0) for item in documents if _successful_backend(item, "neo4j")
        ),
        orphan_document_count=len(orphan_ids),
        milvus=milvus,
        neo4j=neo4j,
        state_counts=dict(state_counts),
        document_checks=checks[:DOCUMENT_CHECK_LIMIT],
        document_checks_complete=(
            len(checks) <= DOCUMENT_CHECK_LIMIT and milvus.scan_complete and neo4j.scan_complete
        ),
        observation_note=(
            "切片期望值来自当前租户文档元数据，实际值来自实时索引查询。"
            "本页不是检索质量评测；后端不可用或扫描超限时，文档级结果标记为未知。"
        ),
    )
    await append_audit_event(
        session,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        source="api",
        action="knowledge.index_runtime_read",
        resource_type="knowledge_index",
        resource_id=current_user.tenant_id,
        outcome="success",
        request_id=request_id_var.get(),
        metadata={
            "milvus_available": milvus.available,
            "neo4j_available": neo4j.available,
            "document_count": len(documents),
            "mismatch_count": state_counts.get("mismatch", 0),
        },
    )
    return response
