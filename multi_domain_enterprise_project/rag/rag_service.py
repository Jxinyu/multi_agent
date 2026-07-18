import asyncio
import os
import time

from multi_domain_enterprise_project.rag.document_in_database import insert_document
from multi_domain_enterprise_project.rag.exceptions import BackendDeleteError
from multi_domain_enterprise_project.rag.graph.ingestion_graph import (
    get_graph_retriever_service,
    get_graph_store_pipeline_service,
)
from multi_domain_enterprise_project.rag.milvus.ingestion_milvus import (
    get_milvus_retriever_service,
    get_milvus_store_pipeline_service,
)
from multi_domain_enterprise_project.rag.retrieval import (
    format_fused_context,
    fuse_backend_results,
)


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
    # 构建过滤metadata
    filters = {
        "title": title,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "acl": acl_list,
    }

    if not query_str:
        return "请输入检索内容"
    if mode == "milvus":
        ingestion = get_milvus_retriever_service()
        query = await ingestion.retrieve_answer(query_str, filters)
    elif mode == "graph":
        ingestion = get_graph_retriever_service()
        query = await ingestion.retrieve_answer(query_str, filters)
    elif mode == "mg":
        milvus_retriever = get_milvus_retriever_service()
        graph_retriever = get_graph_retriever_service()
        milvus_nodes, graph_nodes = await asyncio.gather(
            milvus_retriever.retrieve_nodes(query_str, filters),
            graph_retriever.retrieve_nodes(query_str, filters),
        )
        query = format_fused_context(
            fuse_backend_results({"milvus": milvus_nodes, "neo4j": graph_nodes})
        )
    else:
        raise ValueError(f"不支持的检索模式: {mode}")

    if not query:
        return "检索的结果为空"
    return query


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
