import asyncio
import hashlib
import logging
import re
from functools import lru_cache

from llama_index.core import PropertyGraphIndex
from llama_index.core.graph_stores.types import EntityNode, Relation
from llama_index.core.indices.property_graph import SimpleLLMPathExtractor, VectorContextRetriever
from llama_index.core.schema import BaseNode
from llama_index.embeddings.langchain import LangchainEmbedding
from llama_index.llms.dashscope import DashScope

from config import settings
from multi_domain_enterprise_project.rag.authorization import (
    build_authorized_filter_branches,
    filter_authorized_nodes,
)
from multi_domain_enterprise_project.rag.graph.graph_db import get_graph_store
from multi_domain_enterprise_project.rag.ollama_embedding import ollama_embedding_function
from multi_domain_enterprise_project.rag.retrieval import deduplicate_node_results
from multi_domain_enterprise_project.rag.runtime import rerank_nodes

logger = logging.getLogger(__name__)


class TenantScopedLLMPathExtractor(SimpleLLMPathExtractor):
    """避免同名图实体在不同文档之间共享授权边界。"""

    async def _aextract(self, node: BaseNode) -> BaseNode:
        node = await super()._aextract(node)
        tenant_id = str(node.metadata.get("tenant_id") or "")
        document_id = str(node.metadata.get("document_id") or "")
        version = str(node.metadata.get("version", 1))
        if not tenant_id or not document_id:
            raise ValueError("图谱抽取节点缺少 tenant_id 或 document_id")

        scope = hashlib.sha256(
            f"{tenant_id}\0{document_id}\0{version}".encode()
        ).hexdigest()[:16]
        entity_map = {}
        scoped_entities = []
        for entity in node.metadata.get("nodes", []):
            if not isinstance(entity, EntityNode):
                scoped_entities.append(entity)
                continue
            scoped_entity = EntityNode(
                name=f"{scope}::{entity.name}",
                label=entity.label,
                embedding=entity.embedding,
                properties={**entity.properties, "entity_name": entity.name},
            )
            entity_map[entity.id] = scoped_entity.id
            scoped_entities.append(scoped_entity)

        scoped_relations = []
        for relation in node.metadata.get("relations", []):
            if not isinstance(relation, Relation):
                scoped_relations.append(relation)
                continue
            scoped_relations.append(
                Relation(
                    label=relation.label,
                    source_id=entity_map.get(relation.source_id, relation.source_id),
                    target_id=entity_map.get(relation.target_id, relation.target_id),
                    properties=relation.properties,
                )
            )
        node.metadata["nodes"] = scoped_entities
        node.metadata["relations"] = scoped_relations
        return node


@lru_cache(maxsize=1)
def get_graph_embedding_model() -> LangchainEmbedding:
    return LangchainEmbedding(ollama_embedding_function)


@lru_cache(maxsize=1)
def get_graph_llm() -> DashScope:
    return DashScope(model_name="qwen-max", api_key=settings.llm_key.qwen)


class GraphStorePipelineService:
    def __init__(self):
        # 1. 准备 Embedding
        self.embed_model = get_graph_embedding_model()

        # 2. 准备大语言模型 (用于抽取，推荐用大参数模型)
        self.llm = get_graph_llm()

        # 3. 配置图谱存储
        self.graph_store = get_graph_store()

        # 4. 配置三元组抽取器
        # SimpleLLMPathExtractor 会提取实体及其关联，构建诸如 (李四, 汇报给, 张三) 的关系
        self.kg_extractor = TenantScopedLLMPathExtractor(
            llm=self.llm,
            max_paths_per_chunk=10,  # 每个文本块最多抽取10个关系
            num_workers=2  # 并发抽取
        )

    async def insert_nodes(self, nodes: list[BaseNode]):
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
            PropertyGraphIndex(
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

    async def delete_document(self, tenant_id: str, document_id: str) -> None:
        if not tenant_id or not document_id:
            raise ValueError("删除 Neo4j 数据必须提供 tenant_id 和 document_id")
        await asyncio.to_thread(
            self.graph_store.delete,
            properties={"tenant_id": tenant_id, "document_id": document_id},
        )


class GraphRetrieverService:
    def __init__(self):
        # 1. 准备 Embedding
        self.embed_model = get_graph_embedding_model()

        # 2. 准备大语言模型 (用于抽取，推荐用大参数模型)
        self.llm = get_graph_llm()

        # 3. 配置图谱存储
        self.graph_store = get_graph_store()

        # 获取数据库索引，用于检索
        self.index = PropertyGraphIndex.from_existing(
            property_graph_store=self.graph_store,
            llm=self.llm,
            embed_model=self.embed_model,
        )

    async def retrieve_candidates(self, query_str: str, filters_dict: dict = None):
        logger.info("正在向 Neo4j 发起授权检索")
        scope, filter_branches = build_authorized_filter_branches(filters_dict)
        retrievers = [
            VectorContextRetriever(
                self.index.property_graph_store,
                embed_model=self.embed_model,
                include_text=True,
                similarity_top_k=settings.retrieval.candidate_top_k,
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
        return await format_graph_retrieval_results(
            await self.retrieve_nodes(query_str, filters_dict)
        )


async def format_graph_retrieval_results(
    nodes,
    *,
    max_chars: int | None = None,
    max_chunks_per_document: int | None = None,
):
    """
    格式化 GraphRAG 检索结果：将三元组与文本块区分，但保持 Header 风格一致
    """
    if not nodes:
        return "【图数据库检索】: 未找到相关关联事实。"

    kg_parts = ["### 🕸️ 知识图谱关联事实："]
    text_parts = ["### 📄 图谱关联参考文本："]
    max_chars = settings.retrieval.max_context_chars if max_chars is None else max_chars
    max_chunks_per_document = (
        settings.retrieval.max_chunks_per_document
        if max_chunks_per_document is None
        else max_chunks_per_document
    )
    if max_chars < 1 or max_chunks_per_document < 1:
        raise ValueError("上下文长度和单文档切片数必须大于 0")
    document_counts = {}

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
        content = re.sub(r"\b[a-f0-9]{16}::", "", node.get_content().strip())

        # 判定是三元组事实还是原始文本
        if "facts extracted from the provided text" in content:
            # 这里的 content 已经包含了 "Here are some facts..."
            header = f"--- [来源: {file_name} | 类型: 关系事实 | 匹配分值: {score_text}] ---"
            section = f"{header}\n{content}"
            if len("\n\n".join((*kg_parts, *text_parts, section))) <= max_chars:
                kg_parts.append(section)
                document_counts[document_key] = document_counts.get(document_key, 0) + 1
        else:
            header = f"--- [来源: {file_name} | 类型: 关联文本 | 匹配分值: {score_text}] ---"
            section = f"{header}\n{content}"
            if len("\n\n".join((*kg_parts, *text_parts, section))) <= max_chars:
                text_parts.append(section)
                document_counts[document_key] = document_counts.get(document_key, 0) + 1

    # 合并输出
    result = []
    if len(kg_parts) > 1:
        result.append("\n\n".join(kg_parts))
    if len(text_parts) > 1:
        result.append("\n\n".join(text_parts))

    return "\n\n".join(result) if result else "【图数据库检索】: 未找到相关关联事实。"


@lru_cache(maxsize=1)
def get_graph_store_pipeline_service() -> GraphStorePipelineService:
    return GraphStorePipelineService()


@lru_cache(maxsize=1)
def get_graph_retriever_service() -> GraphRetrieverService:
    return GraphRetrieverService()
