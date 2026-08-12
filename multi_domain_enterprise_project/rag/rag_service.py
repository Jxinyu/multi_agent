import asyncio
import os
import time

from config import settings
from multi_domain_enterprise_project.core.observability import (
    RETRIEVAL_CANDIDATES,
    RETRIEVAL_FUSED_CANDIDATES,
    RETRIEVAL_LATENCY,
    RETRIEVAL_REQUESTS,
    RETRIEVAL_RERANK_LATENCY,
    RETRIEVAL_RESULTS,
)
from multi_domain_enterprise_project.rag.authorization import (
    RetrievalAuthorization,
    filter_authorized_nodes,
)
from multi_domain_enterprise_project.rag.document_in_database import insert_document
from multi_domain_enterprise_project.rag.exceptions import BackendDeleteError, RetrievalTimeoutError
from multi_domain_enterprise_project.rag.graph.ingestion_graph import (
    format_graph_retrieval_results,
    get_graph_retriever_service,
    get_graph_store_pipeline_service,
)
from multi_domain_enterprise_project.rag.milvus.ingestion_milvus import (
    format_milvus_context,
    get_milvus_retriever_service,
    get_milvus_store_pipeline_service,
)
from multi_domain_enterprise_project.rag.retrieval import (
    attach_reranked_provenance,
    format_fused_context,
    fuse_backend_results,
)
from multi_domain_enterprise_project.rag.runtime import rerank_nodes


async def _retrieve_backend_candidates(backend: str, retriever, query_str: str, filters: dict):
    try:
        candidates = await asyncio.wait_for(
            retriever.retrieve_candidates(query_str, filters),
            timeout=settings.retrieval.timeout_seconds,
        )
    except TimeoutError as exc:
        raise RetrievalTimeoutError(
            f"{backend} 检索超过 {settings.retrieval.timeout_seconds:g} 秒"
        ) from exc
    RETRIEVAL_CANDIDATES.labels(backend=backend).observe(len(candidates))
    return candidates


async def _rerank_candidates(query_str: str, candidates: list):
    try:
        return await asyncio.wait_for(
            rerank_nodes(query_str, candidates),
            timeout=settings.retrieval.timeout_seconds,
        )
    except TimeoutError as exc:
        raise RetrievalTimeoutError(
            f"重排超过 {settings.retrieval.timeout_seconds:g} 秒"
        ) from exc


async def retrieve_service(query_str: str, title: str = None, tenant_id: str = None, acl_list: list = None,
                           mode: str = "milvus", user_id: str = None) -> str:
    """
    知识库检索服务
    :param query_str: 检索内容
    :param tenant_id: 租户id
    :param title: 文档标题
    :param acl_list: 可访问权限
    :param user_id: 当前用户 id，用于 owner 与 ACL 联合授权
    :param mode: 默认是 'milvus' 表示检索向量数据库；'graph' 表示检索知识图谱; 'mg': 表示检索向量数据库+知识图谱;
    :return:
    """
    if not query_str or not query_str.strip():
        return "请输入检索内容"
    if mode not in {"milvus", "graph", "mg"}:
        raise ValueError(f"不支持的检索模式: {mode}")

    filters = {
        "title": title,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "acl": acl_list,
    }
    scope = RetrievalAuthorization.from_filters(filters)
    started = time.perf_counter()
    request_status = "failed"
    try:
        retrievers = {}
        if mode in {"milvus", "mg"}:
            retrievers["milvus"] = get_milvus_retriever_service()
        if mode in {"graph", "mg"}:
            retrievers["neo4j"] = get_graph_retriever_service()
        candidate_groups = await asyncio.gather(
            *(
                _retrieve_backend_candidates(backend, retriever, query_str, filters)
                for backend, retriever in retrievers.items()
            )
        )
        backend_results = dict(zip(retrievers, candidate_groups, strict=True))
        fused_candidates = fuse_backend_results(
            backend_results,
            rrf_k=settings.retrieval.rrf_k,
            limit=settings.retrieval.fusion_candidate_limit,
        )
        RETRIEVAL_FUSED_CANDIDATES.labels(mode=mode).observe(len(fused_candidates))
        rerank_started = time.perf_counter()
        try:
            reranked_nodes = await _rerank_candidates(
                query_str,
                [candidate.node_with_score for candidate in fused_candidates],
            )
        finally:
            RETRIEVAL_RERANK_LATENCY.labels(mode=mode).observe(
                time.perf_counter() - rerank_started
            )
        reranked_nodes = filter_authorized_nodes(reranked_nodes, scope)
        RETRIEVAL_RESULTS.labels(mode=mode).observe(len(reranked_nodes))

        if mode == "milvus":
            query = await format_milvus_context(
                reranked_nodes,
                max_chars=settings.retrieval.max_context_chars,
                max_chunks_per_document=settings.retrieval.max_chunks_per_document,
            )
        elif mode == "graph":
            query = await format_graph_retrieval_results(
                reranked_nodes,
                max_chars=settings.retrieval.max_context_chars,
                max_chunks_per_document=settings.retrieval.max_chunks_per_document,
            )
        else:
            query = format_fused_context(
                attach_reranked_provenance(reranked_nodes, fused_candidates),
                max_chars=settings.retrieval.max_context_chars,
                max_chunks_per_document=settings.retrieval.max_chunks_per_document,
            )
        request_status = "success"
        return query or "检索的结果为空"
    finally:
        RETRIEVAL_REQUESTS.labels(mode=mode, status=request_status).inc()
        RETRIEVAL_LATENCY.labels(mode=mode).observe(time.perf_counter() - started)


async def insert_service(file_path: str, tenant_id: str, user_id: str, title: str, acl: str,
                         mode: str = "milvus", document_id: str = None,
                         version: int | str = 1) -> int:
    """
    文档传入知识库服务
    :param file_path: 文档路径
    :param tenant_id: 租户id
    :param user_id: 用户id
    :param title: 文档标题
    :param acl: 可访问权限
    :param mode: 默认是 'milvus' 表示检索向量数据库；'graph' 表示检索知识图谱; 'mg': 表示检索向量数据库+知识图谱;
    :return:
    """
    # 构建元数据
    file_name = os.path.basename(file_path)  # 文件名
    metadata = {
        "file_name": str(file_name),
        "file_path": str(file_path),

        "tenant_id": str(tenant_id),
        "owner_id": str(user_id),
        "document_id": str(document_id) if document_id else None,
        "version": version,

        "title": str(title),  # 文档标题

        "acl": str(acl),  # 最低访问权限

        "upload_time": str(time.strftime("%Y-%m-%d %H:%M:%S")),
    }
    return await insert_document(metadata, mode)


async def delete_document_data(
    tenant_id: str,
    document_id: str,
    mode: str = "mg",
) -> dict[str, dict[str, str | None]]:
    """按租户和文档 id 删除一个或两个 RAG 后端中的数据。"""
    tenant_id = str(tenant_id or "").strip()
    document_id = str(document_id or "").strip()
    if not tenant_id or not document_id:
        raise ValueError("删除文档数据必须提供 tenant_id 和 document_id")

    operations = {}
    if mode in {"milvus", "mg"}:
        operations["milvus"] = get_milvus_store_pipeline_service().delete_document(
            tenant_id, document_id
        )
    if mode in {"graph", "mg"}:
        operations["neo4j"] = get_graph_store_pipeline_service().delete_document(
            tenant_id, document_id
        )
    if not operations:
        raise ValueError(f"不支持的删除模式: {mode}")

    results = await asyncio.gather(*operations.values(), return_exceptions=True)
    backend_status = {}
    for backend, result in zip(operations, results, strict=True):
        if isinstance(result, Exception):
            backend_status[backend] = {"status": "failed", "error": str(result)}
        else:
            backend_status[backend] = {"status": "success", "error": None}
    if any(item["status"] == "failed" for item in backend_status.values()):
        raise BackendDeleteError(backend_status)
    return backend_status
