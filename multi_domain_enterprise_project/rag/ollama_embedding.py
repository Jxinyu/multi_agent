from config import settings
from ollama import Client, AsyncClient
from langchain_core.embeddings import Embeddings
from typing import List

# 异步客户端，用于 aembed_* 方法
ollama_async_client = AsyncClient(host=settings.ollama.base_url)
# 同步客户端，用于 embed_* 方法
ollama_sync_client = Client(host=settings.ollama.base_url)


class OllamaEmbeddings(Embeddings):
    """
    一个使用Ollama本地模型并兼容LangChain的自定义Embedding类。
    """
    model_name: str = settings.ollama.embedding_model

    async def aembed_documents(self, texts: List[str], dims: int = settings.milvus.dims) -> List[List[float]]:
        """异步地为一组文档生成向量"""
        # 使用异步客户端
        response = await ollama_async_client.embed(
            model=self.model_name,
            input=texts,
            dimensions=dims
        )
        return response['embeddings']

    async def aembed_query(self, text: str, dims: int = settings.milvus.dims) -> List[float]:
        """异步地为单个查询文本生成向量"""
        # 使用异步客户端
        response = await ollama_async_client.embed(
            model=self.model_name,
            input=text,
            dimensions=dims
        )
        return response['embeddings'][0]

    def embed_documents(self, texts: List[str], dims: int = settings.milvus.dims) -> List[List[float]]:
        """同步地为一组文档生成向量"""
        response = ollama_sync_client.embed(
            model=self.model_name,
            input=texts,
            dimensions=dims
        )
        return response['embeddings']

    def embed_query(self, text: str, dims: int = settings.milvus.dims) -> List[float]:
        """同步地为单个查询文本生成向量"""
        response = ollama_sync_client.embed(
            model=self.model_name,
            input=text,
            dimensions=dims
        )
        return response['embeddings'][0]


ollama_embedding_function = OllamaEmbeddings()
