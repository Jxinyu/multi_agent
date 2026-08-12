import asyncio
import logging
from functools import lru_cache

from llama_index.core import VectorStoreIndex
from llama_index.core.schema import BaseNode
from llama_index.core.vector_stores import FilterCondition, FilterOperator, MetadataFilter, MetadataFilters
from llama_index.embeddings.ollama import OllamaEmbedding

from config import settings
from multi_domain_enterprise_project.rag.authorization import (
    build_authorized_filter_branches,
    filter_authorized_nodes,
)
from multi_domain_enterprise_project.rag.milvus.milvus_db import EnterpriseMilvusStore
from multi_domain_enterprise_project.rag.retrieval import deduplicate_node_results
from multi_domain_enterprise_project.rag.runtime import rerank_nodes

logger = logging.getLogger(__name__)


# 全局共享的基础配置获取函数
@lru_cache(maxsize=4)
def get_base_index(collection_name: str):
    """提取公共的连接初始化代码"""
    # 连接本地向量模型
    embed_model = OllamaEmbedding(
        model_name=settings.ollama.embedding_model,
        base_url=settings.ollama.base_url,
    )
    # 创建milvus管理器
    milvus_manager = EnterpriseMilvusStore(
        collection_name=collection_name,
        dim=settings.milvus.dims
    )
    # 获取存储上下文
    storage_context = milvus_manager.get_storage_context()
    # 获取向量索引
    index = VectorStoreIndex.from_vector_store(
        vector_store=storage_context.vector_store,
        embed_model=embed_model
    )
    return index


class MilvusStorePipelineService:
    """数据入库服务 (无状态，轻量级，不加载重排模型)
    """

    def __init__(self, collection_name: str = "company_knowledge_base"):
        self.index = get_base_index(collection_name)

    async def insert_nodes(self, nodes: list[BaseNode], batch_size: int = 100):
        if not nodes:
            return

        logger.info(f"🚀 开始增量入库 {len(nodes)} 个切片 (Batch Size: {batch_size})...")
        try:
            # 批处理写入 防 gRPC 超载
            for i in range(0, len(nodes), batch_size):
                batch = nodes[i: i + batch_size]
                # 因为 node.id_ 是 hash，Milvus 会执行 Upsert，自动去重更新！
                await self.index.ainsert_nodes(batch)
                logger.info(f"   -> 成功写入批次 {i // batch_size + 1}")

            logger.info("✅ 全量入库成功！")
        except Exception as e:
            logger.error(f"❌ 入库失败: {e}")
            raise

    async def delete_document(self, tenant_id: str, document_id: str) -> None:
        if not tenant_id or not document_id:
            raise ValueError("删除 Milvus 数据必须提供 tenant_id 和 document_id")
        filters = MetadataFilters(
            filters=[
                MetadataFilter(key="tenant_id", value=tenant_id, operator=FilterOperator.EQ),
                MetadataFilter(key="document_id", value=document_id, operator=FilterOperator.EQ),
            ],
            condition=FilterCondition.AND,
        )
        await asyncio.to_thread(self.index.vector_store.delete_nodes, filters=filters)


class MilvusRetrieverService:
    """
    检索服务 (常驻内存，仅初始化一次 Reranker)
    """

    def __init__(self, collection_name: str = "company_knowledge_base"):
        self.index = get_base_index(collection_name)

    async def retrieve_candidates(self, query_str: str, filters_dict: dict = None):
        """
        检索数据库
        :param query_str: 搜索的内容
        :param filters_dict: 按字段过滤
        :return:
        """
        logger.info("正在向 Milvus 发起授权检索")
        scope, filter_branches = build_authorized_filter_branches(filters_dict)
        retrievers = [
            self.index.as_retriever(
                similarity_top_k=settings.retrieval.candidate_top_k,
                vector_store_query_mode="hybrid",
                filters=filters,
            )
            for filters in filter_branches
        ]
        branch_results = await asyncio.gather(
            *(retriever.aretrieve(query_str) for retriever in retrievers)
        )
        final_nodes = deduplicate_node_results(
            [node for branch in branch_results for node in branch]
        )
        final_nodes = filter_authorized_nodes(final_nodes, scope)[: settings.retrieval.backend_candidate_limit]

        if not final_nodes:
            logger.warning("⚠️ 检索结果为空！")
            return []

        return final_nodes

    async def retrieve_nodes(self, query_str: str, filters_dict: dict = None):
        scope, _ = build_authorized_filter_branches(filters_dict)
        candidates = await self.retrieve_candidates(query_str, filters_dict)
        return filter_authorized_nodes(await rerank_nodes(query_str, candidates), scope)

    async def retrieve_answer(self, query_str: str, filters_dict: dict = None):
        return await format_milvus_context(await self.retrieve_nodes(query_str, filters_dict))


async def format_milvus_context(nodes, *, max_chars: int | None = None, max_chunks_per_document: int | None = None):
    """
    格式化 Milvus 向量检索结果：统一 Header 风格
    """
    if not nodes:
        return "【向量库检索】: 未找到相关参考资料。"

    context_parts = ["### 📚 向量库参考文档："]
    max_chars = settings.retrieval.max_context_chars if max_chars is None else max_chars
    max_chunks_per_document = (
        settings.retrieval.max_chunks_per_document
        if max_chunks_per_document is None
        else max_chunks_per_document
    )
    if max_chars < 1 or max_chunks_per_document < 1:
        raise ValueError("上下文长度和单文档切片数必须大于 0")
    document_counts = {}

    # 按照分值排序并去重
    seen_ids = set()
    for node_with_score in nodes:
        node = node_with_score.node
        if node.node_id in seen_ids:
            continue
        seen_ids.add(node.node_id)
        document_key = str(node.metadata.get("document_id") or node.metadata.get("file_name") or node.node_id)
        if document_counts.get(document_key, 0) >= max_chunks_per_document:
            continue

        score = node_with_score.score
        score_text = f"{score:.4f}" if score is not None else "N/A"
        file_name = node.metadata.get('file_name', '未知文件')
        content = node.get_content().strip()

        # 统一 Header 样式
        header = f"--- [来源: {file_name} | 类型: 原始文本块 | 匹配分值: {score_text}] ---"
        section = f"{header}\n{content}"
        if len("\n\n".join((*context_parts, section))) > max_chars:
            continue
        context_parts.append(section)
        document_counts[document_key] = document_counts.get(document_key, 0) + 1

    return "\n\n".join(context_parts) if len(context_parts) > 1 else "【向量库检索】: 未找到相关参考资料。"


@lru_cache(maxsize=4)
def get_milvus_store_pipeline_service(
    collection_name: str = "company_knowledge_base",
) -> MilvusStorePipelineService:
    return MilvusStorePipelineService(collection_name)


@lru_cache(maxsize=4)
def get_milvus_retriever_service(
    collection_name: str = "company_knowledge_base",
) -> MilvusRetrieverService:
    return MilvusRetrieverService(collection_name)
