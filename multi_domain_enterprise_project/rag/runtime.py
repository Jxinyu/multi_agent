import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Any

from llama_index.core import QueryBundle
from llama_index.postprocessor.flag_embedding_reranker import FlagEmbeddingReranker

from config import settings

_RERANK_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-reranker")


@lru_cache(maxsize=1)
def get_reranker() -> FlagEmbeddingReranker:
    model = settings.reranker.model_path.strip()
    if not model:
        raise RuntimeError("RERANKER_MODEL_PATH 未配置")
    if model.startswith(("/", ".")) and not Path(model).is_dir():
        raise RuntimeError("RERANKER_MODEL_PATH 指向的模型目录不存在")
    return FlagEmbeddingReranker(
        top_n=settings.reranker.top_n,
        model=model,
        use_fp16=settings.reranker.use_fp16,
    )


async def rerank_nodes(query_str: str, nodes: list[Any]) -> list[Any]:
    """在专用线程执行重排，避免阻塞事件循环和公共线程池。"""
    if not nodes:
        return []
    query_bundle = QueryBundle(query_str=query_str)

    def run() -> list[Any]:
        return get_reranker().postprocess_nodes(nodes=nodes, query_bundle=query_bundle)

    return await asyncio.get_running_loop().run_in_executor(_RERANK_EXECUTOR, run)
