import asyncio
import os
import logging
import re
from pathlib import Path

from multi_domain_enterprise_project.rag.documentParser.parser_route import DocumentParserRouter
from multi_domain_enterprise_project.rag.chunker import EnterpriseDocumentChunker
from multi_domain_enterprise_project.rag.graph.ingestion_graph import GraphStorePipelineService
from multi_domain_enterprise_project.rag.milvus.ingestion_milvus import MilvusStorePipelineService
from multi_domain_enterprise_project.rag.kb_admin import KnowledgeDocument, create_document_id, upsert_document

import short_unique_id as suid

logger = logging.getLogger(__name__)


async def get_snowflake_id() -> str:
    """
    生成一个随机的 snowflake ID
    """
    return str(suid.get_next_snowflake_id())


async def _clean_markdown_wrapper(text: str) -> str:
    """
    清洗解析器可能附带的 ```markdown ... ``` 外套
    """
    text = text.strip()
    # 使用正则匹配，兼容 ```markdown, ```md, 或者仅有 ``` 开头的情况
    # re.DOTALL 使得 . 可以匹配换行符
    pattern = r"^```(?:markdown|md)?\s*\n(.*?)\n```$"
    match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)

    if match:
        logger.info("🧹 检测到 ```markdown 外套，已自动剥离！")
        return match.group(1).strip()

    # 兜底：如果没匹配上正则，但确实以 ``` 开头和结尾（比如没有换行的情况）
    if text.startswith("```") and text.endswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("markdown"):
            text = text[8:].strip()
        elif text.lower().startswith("md"):
            text = text[2:].strip()
        logger.info("🧹 执行了基础的 markdown 外套剥离！")
        return text

    return text


async def clean_document_str(file_path: str, tenant_id: str):
    """
    获取文档的md格式文本
    :param file_path: 文档的存储路径
    :param tenant_id: 文档所属的租户
    :return:
    """
    file_name = os.path.basename(file_path)
    logger.info(f"\n⚡ [Start] 开始处理文件: {file_name}")
    router = DocumentParserRouter(mode="auto")
    try:
        # 获取md文本
        markdown_text = await router.route_and_parse(file_path)
        # 格式化md文本
        markdown_text = await _clean_markdown_wrapper(markdown_text)
        # 存储md文本
        file_path_md = Path(f"./data/{tenant_id}/{await get_snowflake_id()}.md")
        file_path_md.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path_md, 'w', encoding='utf-8') as f:
            f.write(markdown_text)
        return markdown_text, file_path_md
    except Exception as e:
        logger.error(f"❌ 解析阶段失败: {e}")
        return None, None


async def insert_document(metadata: dict, mode: str = "milvus"):
    """
    RAG ETL 主流程：文件 -> 解析 -> 切片 -> 向量化 -> 存储
    file_path: 文件存储路径
    tenant_id: 租户id  部门
    user_id: 用户id  用户账号
    title: 文档标题
    acl: 最低访问权限
    mode: 默认是 'milvus' 表示检索向量数据库；'graph' 表示检索知识图谱; 'mg': 表示检索向量数据库+知识图谱;
    """
    file_name = metadata["file_name"]

    # --- Step 1: 智能路由解析 获取文档的md格式---
    markdown_text, file_path_md = await clean_document_str(metadata["file_path"], metadata["tenant_id"])
    metadata["file_path_md"] = file_path_md

    # --- Step 2: 级联切片 ---
    chunker = EnterpriseDocumentChunker(chunk_size=512, chunk_overlap=50)
    nodes = chunker.split_text(markdown_text, metadata=metadata)

    if not nodes:
        logger.warning("⚠️ 切片结果为空，流程终止。")
        return
    logger.info(f"✅ 切片完成: {len(nodes)} 个节点")

    # --- Step 3: 向量化与存储 (Milvus/graph neo4j) ---
    if mode == "milvus":
        milvus_ingestion = MilvusStorePipelineService()
        logger.info(f"🚀 开始对 {file_name} 执行入库 (Milvus向量库 )...")
        await milvus_ingestion.insert_nodes(nodes)  # 插入数据
        logger.info(f"🎉 [Success] 文件 {file_name} 处理完毕，数据已入库！")
    elif mode == "graph":
        logger.info(f"🚀 开始对 {file_name} 执行并发入库 (Neo4j 图数据库)...")
        graph_ingestion = GraphStorePipelineService()
        await graph_ingestion.insert_nodes(nodes)
        logger.info(f"🎉 [Success] 文件 {file_name} 处理完毕，数据已入库！")
    else:
        logger.info(f"🚀 开始对 {file_name} 执行双路并发入库 (Milvus 向量库 & Neo4j 图数据库)...")
        # 如果是图文双路入库模式
        milvus_ingestion = MilvusStorePipelineService()
        graph_ingestion = GraphStorePipelineService()
        try:
            # 使用 asyncio.gather 并发执行，return_exceptions=True 保证一个失败不影响另一个
            results = await asyncio.gather(
                milvus_ingestion.insert_nodes(nodes),
                graph_ingestion.insert_nodes(nodes),
                return_exceptions=True
            )
            # 遍历检查并发任务中是否有异常抛出
            has_error = False
            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    has_error = True
                    failed_service = "Milvus 入库" if i == 0 else "Neo4j 图谱入库"
                    logger.error(f"❌ {failed_service} 发生异常: {res}")
            if not has_error:
                logger.info(f"🎉 [Success] 文件 {file_name} 处理完毕，Milvus 与 Neo4j 双路入库均成功！")
            else:
                logger.warning(f"⚠️ 文件 {file_name} 入库完成，但部分服务存在异常，请检查上方日志。")

        except Exception as e:
            logger.error(f"❌ 双路入库调度阶段发生致命错误: {e}")
