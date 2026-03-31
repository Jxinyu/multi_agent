import logging
from typing import List

from llama_index.core import PropertyGraphIndex
from llama_index.core.schema import BaseNode, QueryBundle
from llama_index.core.indices.property_graph import SimpleLLMPathExtractor, LLMSynonymRetriever, VectorContextRetriever
from llama_index.core.vector_stores import MetadataFilter, FilterOperator, MetadataFilters, FilterCondition
from llama_index.embeddings.langchain import LangchainEmbedding
from llama_index.llms.dashscope import DashScope
from llama_index.llms.openai_like import OpenAILike
from llama_index.postprocessor.flag_embedding_reranker import FlagEmbeddingReranker

from config import settings
from multi_domain_enterprise_project.rag.graph.graph_db import EnterpriseGraphStore
from multi_domain_enterprise_project.rag.ollama_embedding import ollama_embedding_function

logger = logging.getLogger(__name__)


class GraphStorePipelineService:
    def __init__(self):
        # 1. 准备 Embedding
        self.embed_model = LangchainEmbedding(ollama_embedding_function)

        # 2. 准备大语言模型 (用于抽取，推荐用大参数模型)
        self.llm = DashScope(
            model_name="qwen-max",
            api_key=settings.llm_key.qwen
        )

        # 3. 配置图谱存储
        self.graph_store = EnterpriseGraphStore().get_graph_store()

        # 4. 配置三元组抽取器
        # SimpleLLMPathExtractor 会提取实体及其关联，构建诸如 (李四, 汇报给, 张三) 的关系
        self.kg_extractor = SimpleLLMPathExtractor(
            llm=self.llm,
            max_paths_per_chunk=10,  # 每个文本块最多抽取10个关系
            num_workers=2  # 并发抽取
        )

    async def insert_nodes(self, nodes: List[BaseNode]):
        """执行图谱抽取和入库"""
        if not nodes:
            return

        logger.info(f"🚀 开始 GraphRAG 知识抽取与入库，共 {len(nodes)} 个切片...")

        for node in nodes:
            for key, value in list(node.metadata.items()):
                # 1. 如果是空值，Neo4j不支持，直接删除该键
                if value is None:
                    del node.metadata[key]
                    continue

                # 2. 如果是列表，遍历列表里的每个元素
                if isinstance(value, list):
                    cleaned_list = []
                    for item in value:
                        # 只要不是(字符串, 整数, 浮点数, 布尔值)，统统强转为字符串
                        if not isinstance(item, (str, int, float, bool)):
                            cleaned_list.append(str(item))
                        else:
                            cleaned_list.append(item)
                    node.metadata[key] = cleaned_list

                # 3. 如果是单值，且不是基础类型（比如 WindowsPath, dict 等），直接转为字符串
                elif not isinstance(value, (str, int, float, bool)):
                    node.metadata[key] = str(value)

        try:
            # PropertyGraphIndex.from_nodes 会自动执行:
            # 文本块 -> 抽取器(LLM) -> 生成图结构 -> 向量化实体/文本块 -> 存入图数据库
            index = PropertyGraphIndex(
                nodes,  # 节点列表
                llm=self.llm,  # LLM
                use_async=True,  # 异步执行
                embed_model=self.embed_model,
                kg_extractors=[self.kg_extractor],  # 三元组抽取器
                property_graph_store=self.graph_store,  # 图谱存储
                show_progress=True,  # 显示进度
            )
            logger.info("✅ GraphRAG 图谱全量入库成功！")
        except Exception as e:
            logger.error(f"❌ 图谱入库失败: {e}")
            raise


class GraphRetrieverService:
    def __init__(self):
        # 1. 准备 Embedding
        self.embed_model = LangchainEmbedding(ollama_embedding_function)

        # 2. 准备大语言模型 (用于抽取，推荐用大参数模型)
        self.llm = DashScope(
            model_name="qwen-max",
            api_key=settings.llm_key.qwen
        )

        # 3. 配置图谱存储
        self.graph_store = EnterpriseGraphStore().get_graph_store()

        # 获取数据库索引，用于检索
        self.index = PropertyGraphIndex.from_existing(
            property_graph_store=self.graph_store,
            llm=self.llm,
            embed_model=self.embed_model,
        )

        # BGE-Reranker 来精排子图和文本
        self.reranker = FlagEmbeddingReranker(
            top_n=3, model="D:/Environment/model/bge-reranker-v2-m3", use_fp16=True
        )

    async def retrieve_answer(self, query_str: str, filters_dict: dict = None):
        logger.info(f"⚙️ 正在向 Neo4j 图数据库 发起混合检索: {query_str}。 过滤字段: {filters_dict}")

        filters = None
        # 构造元数据过滤器
        if filters_dict:
            # 先把字典里 value 为 None 的键值对剔除掉！
            cleaned_filters = {str(k): str(v) for k, v in filters_dict.items() if v is not None}

            if cleaned_filters:
                filter_list = [
                    MetadataFilter(key=k, value=v, operator=FilterOperator.IN if k == 'acl' else FilterOperator.EQ)
                    for k, v in cleaned_filters.items()
                ]

                filters = MetadataFilters(
                    filters=filter_list,
                    condition=FilterCondition.AND
                )

        # 策略 1: 基于 LLM 的同义词扩展和图谱实体  关键词检索
        synonym_retriever = LLMSynonymRetriever(
            self.index.property_graph_store,
            llm=self.llm,
            include_text=True
        )

        # 策略 2: 基于向量的图谱内容检索 (匹配节点描述或边描述)  向量语义检索
        vector_retriever = VectorContextRetriever(
            self.index.property_graph_store,
            embed_model=self.embed_model,
            include_text=True,
            similarity_top_k=30,
            filters=filters
        )

        # 构建自定义检索器 (LlamaIndex 自带的混合检索功能)
        hybrid_retriever = self.index.as_retriever(
            sub_retrievers=[synonym_retriever, vector_retriever]
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

        return await format_graph_retrieval_results(final_nodes)


async def format_graph_retrieval_results(nodes):
    """
    格式化 GraphRAG 检索结果：将三元组与文本块区分，但保持 Header 风格一致
    """
    if not nodes:
        return "【图数据库检索】: 未找到相关关联事实。"

    kg_parts = ["### 🕸️ 知识图谱关联事实："]
    text_parts = ["### 📄 图谱关联参考文本："]

    seen_ids = set()
    for node_with_score in nodes:
        node = node_with_score.node
        if node.node_id in seen_ids: continue
        seen_ids.add(node.node_id)

        score = node_with_score.score
        file_name = node.metadata.get('file_name', '未知文件')
        content = node.get_content().strip()

        # 判定是三元组事实还是原始文本
        if "facts extracted from the provided text" in content:
            # 这里的 content 已经包含了 "Here are some facts..."
            header = f"--- [来源: {file_name} | 类型: 关系事实 | 匹配分值: {score:.4f}] ---"
            kg_parts.append(f"{header}\n{content}")
        else:
            header = f"--- [来源: {file_name} | 类型: 关联文本 | 匹配分值: {score:.4f}] ---"
            text_parts.append(f"{header}\n{content}")

    # 合并输出
    result = []
    if len(kg_parts) > 1: result.append("\n\n".join(kg_parts))
    if len(text_parts) > 1: result.append("\n\n".join(text_parts))

    return "\n\n".join(result)
