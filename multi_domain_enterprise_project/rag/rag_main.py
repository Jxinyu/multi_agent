import asyncio
import os

import logging

from multi_domain_enterprise_project.rag.document_in_database import insert_document
from multi_domain_enterprise_project.rag.milvus.ingestion_milvus import MilvusRetrieverService

logger = logging.getLogger(__name__)


async def query_milvus_pipeline(query_str: str, filters_dict: dict = None):
    """
     在企业知识库中检索信息。
    Args:
        query_str: 用户的问题或检索语句。
        file_name: 可选，指定文件名（精确匹配）。
        title: 可选，指定文档标题（精确匹配）。
        # 通过上下文注入
        tenant_id: 租户id  部门
        acl: 访问控制列表（通过用户的职别控制）

    Returns:
        检索到的文档片段，用空行分隔。
    """

    ingestion = MilvusRetrieverService()
    query = await ingestion.retrieve_answer(query_str, filters_dict)
    if not query:
        return "检索的结果为空"
    result = "\n\n".join([i.node.get_content() for i in query])
    return result


async def upload_file_to_milvus_pipeline(file_path: str, tenant_id: str, user_id: str, title: str, acl: str,
                                         mode: str = "milvus"):
    """
    RAG ETL 主流程：文件 -> 解析 -> 切片 -> 向量化 -> 存储
    file_path: 文件存储路径
    tenant_id: 租户id  部门
    user_id: 用户id  用户账号
    title: 文档标题
    acl: 访问控制列表（通过用户的职别控制）
    mode: 默认是 'milvus' 表示只入向量数据库；'graph' 表示入向量数据库+构建知识图谱
    """
    from multi_domain_enterprise_project.rag.rag_service import insert_service

    return await insert_service(
        file_path=file_path,
        tenant_id=tenant_id,
        user_id=user_id,
        title=title,
        acl=acl,
        mode=mode,
    )


async def get_all_documents_name(tenant_id: str, acl: str):
    """
    获取所有文档的名称
    """
    logger.info(f"获取所有文档的名称, tenant: {tenant_id}, 权限: {acl}")
    return {
        "": ""
    }


if __name__ == "__main__":
    # 测试文件
    test_files = [
        # r"D:\学习笔记\langchain\rag_upper\document\7181-attention-is-all-you-need.pdf",
        # r"D:\学习笔记\langchain\rag_upper\document\小论文内容整理.docx",
        # r"D:\学习笔记\langchain\rag_upper\document\transformer.png",
        r"D:\学习笔记\langchain\rag_upper\document\rag中处理excel表格.txt"
    ]

    for f in test_files:
        if os.path.exists(f):
            res = asyncio.run(upload_file_to_milvus_pipeline(f, "hr", "admin", "nzqa_institutions_full", "1", "graph"))
            # asyncio.run(query_milvus_pipeline('如何读取excel', {"acl": ["1", "2"], "tenant_id": "hr"}))
        else:
            print(f"文件不存在: {f}")
