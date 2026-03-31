import logging
from typing import List, Dict, Any
from llama_index.core.schema import Document, BaseNode
from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("EnterpriseChunker")


class EnterpriseDocumentChunker:
    """
    企业级级联切片器
    适配了 Router 输出的 Markdown 字符串，自动包装并执行级联切片。
    """

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # 第一把刀：Markdown 结构切片器
        self.md_parser = MarkdownNodeParser()

        # 第二把刀：递归句子切片器 (长度控制器)
        self.text_parser = SentenceSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap
        )

    def split_text(self, markdown_text: str, metadata: Dict[str, Any] = None) -> List[BaseNode]:
        """
        核心方法：接收 Markdown 字符串进行切片
        :param markdown_text: Router 返回的 markdown 文本
        :param metadata: 文件的元数据（如 {"source_file": "合同.pdf"}），用于后续溯源
        """
        if not markdown_text or not markdown_text.strip():
            logger.warning("⚠️ 输入的文本为空，跳过切片。")
            return []

        metadata = metadata or {}

        doc = Document(
            text=markdown_text,
            metadata=metadata
        )

        # 设置元数据不参与 Embedding 计算（防止文件名污染语义空间） 但在检索出结果后，展示给用户时依然可见
        doc.excluded_embed_metadata_keys = list(metadata.keys())

        logger.info(f"🔪 启动级联切片，输入文本长度: {len(markdown_text)} 字符")

        # 1. 第一刀：按 Markdown 结构 (##, ###) 智能切分
        structural_nodes = self.md_parser.get_nodes_from_documents([doc])
        logger.info(f"   ✂️ [结构切片] 生成粗粒度节点: {len(structural_nodes)} 个")

        # 2. 第二刀：对超过 chunk_size 的长文本块，在标点符号处安全截断
        final_nodes = self.text_parser.get_nodes_from_documents(structural_nodes)
        logger.info(f"   ✂️[长度切片] 生成最终安全节点: {len(final_nodes)} 个")

        # 确保幂等性，避免重复向量化
        for node in final_nodes:
            node.id_ = node.hash  # LlamaIndex 自动基于 content 和 metadata 计算的 hash

        return final_nodes




