import logging
from typing import List

from llama_index.core import VectorStoreIndex, QueryBundle
from llama_index.core.schema import BaseNode
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterCondition, FilterOperator
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.postprocessor.flag_embedding_reranker import FlagEmbeddingReranker

from multi_domain_enterprise_project.rag.milvus.milvus_db import EnterpriseMilvusStore
from config import settings

logger = logging.getLogger(__name__)


# 全局共享的基础配置获取函数
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

    async def insert_nodes(self, nodes: List[BaseNode], batch_size: int = 100):
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


class MilvusRetrieverService:
    """
    检索服务 (常驻内存，仅初始化一次 Reranker)
    """

    def __init__(self, collection_name: str = "company_knowledge_base"):
        self.index = get_base_index(collection_name)
        logger.info("⏳ 正在加载 BGE-Reranker 模型至显存...")
        self.reranker = FlagEmbeddingReranker(
            top_n=settings.reranker.top_n,
            model=settings.reranker.model_path,
            use_fp16=settings.reranker.use_fp16
        )
        logger.info("✅ 检索服务初始化完毕！")

    async def retrieve_answer(self, query_str: str, filters_dict: dict = None):
        """
        检索数据库
        :param query_str: 搜索的内容
        :param filters_dict: 按字段过滤
        :return:
        """
        logger.info(f"⚙️ 正在向 Milvus 发起混合检索: {query_str}。 过滤字段: {filters_dict}")
        filters = None
        # 构造元数据过滤器
        if filters_dict:
            # 先把字典里 value 为 None 的键值对剔除掉！
            cleaned_filters = {k: v for k, v in filters_dict.items() if v is not None}

            if cleaned_filters:
                filter_list = [
                    MetadataFilter(key=k, value=v, operator=FilterOperator.IN if k == 'acl' else FilterOperator.EQ)
                    for k, v in cleaned_filters.items()
                ]

                filters = MetadataFilters(
                    filters=filter_list,
                    condition=FilterCondition.AND
                )

        # 必须显式声明 vector_store_query_mode="hybrid", 否则milvus中的 BM25 搜索不生效
        hybrid_retriever = self.index.as_retriever(
            similarity_top_k=30,
            # similarity_top_k=3,
            vector_store_query_mode="hybrid",
            filters=filters
        )

        # 多路召回与融合(内部使用RRF重排)
        final_nodes = await hybrid_retriever.aretrieve(query_str)

        if not final_nodes:
            logger.warning("⚠️ 检索结果为空！")
            return []

        # 2. Reranker 精排
        query_bundle = QueryBundle(query_str=query_str)
        final_nodes = self.reranker.postprocess_nodes(
            nodes=final_nodes,
            query_bundle=query_bundle
        )

        return await format_milvus_context(final_nodes)


async def format_milvus_context(nodes):
    """
    格式化 Milvus 向量检索结果：统一 Header 风格
    """
    if not nodes:
        return "【向量库检索】: 未找到相关参考资料。"

    context_parts = ["### 📚 向量库参考文档："]

    # 按照分值排序并去重
    seen_ids = set()
    for i, node_with_score in enumerate(nodes, 1):
        node = node_with_score.node
        if node.node_id in seen_ids: continue
        seen_ids.add(node.node_id)

        score = node_with_score.score
        file_name = node.metadata.get('file_name', '未知文件')
        content = node.get_content().strip()

        # 统一 Header 样式
        header = f"--- [来源: {file_name} | 类型: 原始文本块 | 匹配分值: {score:.4f}] ---"
        context_parts.append(f"{header}\n{content}")

    return "\n\n".join(context_parts)
