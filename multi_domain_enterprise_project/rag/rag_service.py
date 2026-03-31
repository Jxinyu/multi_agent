import os
import time

from multi_domain_enterprise_project.rag.document_in_database import insert_document
from multi_domain_enterprise_project.rag.graph.ingestion_graph import GraphRetrieverService
from multi_domain_enterprise_project.rag.milvus.ingestion_milvus import MilvusRetrieverService


async def retrieve_service(query_str: str, title: str = None, tenant_id: str = None, acl_list: list = None,
                           mode: str = "milvus") -> str:
    """
    知识库检索服务
    :param query_str: 检索内容
    :param tenant_id: 租户id
    :param title: 文档标题
    :param acl_list: 可访问权限
    :param mode: 默认是 'milvus' 表示检索向量数据库；'graph' 表示检索知识图谱; 'mg': 表示检索向量数据库+知识图谱;
    :return:
    """
    # 构建过滤metadata
    filters = {
        "title": title,
        "tenant_id": tenant_id,
        "acl": acl_list,
    }

    if not query_str:
        return "请输入检索内容"
    if mode == "milvus":
        ingestion = MilvusRetrieverService()
        query = await ingestion.retrieve_answer(query_str, filters)
    elif mode == "graph":
        ingestion = GraphRetrieverService()
        query = await ingestion.retrieve_answer(query_str, filters)
    else:
        # 检索向量数据库和知识图谱
        ingestion_milvus = MilvusRetrieverService()
        query_milvus = await ingestion_milvus.retrieve_answer(query_str, filters)

        ingestion_graph = GraphRetrieverService()
        query_graph = await ingestion_graph.retrieve_answer(query_str, filters)

        query = query_milvus + query_graph

    if not query:
        return "检索的结果为空"
    return query


async def insert_service(file_path: str, tenant_id: str, user_id: str, title: str, acl: str,
                         mode: str = "milvus") -> None:
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

        "title": str(title),  # 文档标题

        "acl": str(acl),  # 最低访问权限

        "upload_time": str(time.strftime("%Y-%m-%d %H:%M:%S")),
    }
    return await insert_document(metadata, mode)
