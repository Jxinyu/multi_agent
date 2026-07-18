from functools import lru_cache
from pathlib import Path

from llama_index.postprocessor.flag_embedding_reranker import FlagEmbeddingReranker

from config import settings


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
