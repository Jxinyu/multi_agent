import logging
from llama_index.vector_stores.milvus import MilvusVectorStore
from llama_index.vector_stores.milvus.utils import BM25BuiltInFunction
from llama_index.core import StorageContext
from config import settings

logger = logging.getLogger(__name__)


class EnterpriseMilvusStore:
    """
    企业级 Milvus 存储管理器
    负责连接管理、集合创建、以及 LlamaIndex 的 StorageContext 封装
    """

    def __init__(self, collection_name: str = "rag_knowledge_base", dim: int = 1536):
        self.collection_name = collection_name
        self.dim = dim
        self.uri = settings.milvus.uri
        # self.token = settings.milvus.token  # 如果是 Zilliz Cloud 需要 token，本地不需要

    def _init_vector_store(self) -> MilvusVectorStore:
        """
        初始化 Milvus 向量存储对象
        LlamaIndex 的 MilvusVectorStore 会自动处理 Schema 创建
        """
        try:
            vector_store = MilvusVectorStore(
                uri=self.uri,
                # token=self.token,
                collection_name=self.collection_name,
                dim=self.dim,
                overwrite=False,  # ⚠️ 生产环境千万别设为 True，否则重启就清空数据
                # 混合检索参数 (可选，企业级建议开启)
                enable_sparse=True,  # 开启稀疏向量（milvus底层默认使用BM25能力）
                # sparse_embedding_function=BM25BuiltInFunction(),  # 显示使用milvus内置的BM25向量搜索
                hybrid_ranker="RRFRanker",  # 告诉 Milvus 在数据库端直接执行 RRF 融合
                hybrid_ranker_params={"k": 60},  # RRF的默认平滑常数
            )
            logger.info(f"✅ 成功连接 Milvus 集合: {self.collection_name} (Dim={self.dim})")
            return vector_store
        except Exception as e:
            logger.error(f"❌ 连接 Milvus 失败: {e}")
            raise

    def get_storage_context(self):
        """获取 LlamaIndex 的存储上下文"""
        vector_store = self._init_vector_store()
        return StorageContext.from_defaults(vector_store=vector_store)
