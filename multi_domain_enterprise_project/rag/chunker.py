import hashlib
import logging
from typing import Any

from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
from llama_index.core.schema import BaseNode, Document

from multi_domain_enterprise_project.rag.exceptions import EmptyDocumentError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("EnterpriseChunker")


def stable_node_id(tenant_id: str, document_id: str, version: Any, chunk_index: int) -> str:
    identity = f"{tenant_id}\0{document_id}\0{version}\0{chunk_index}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


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

    def split_text(self, markdown_text: str, metadata: dict[str, Any] = None) -> list[BaseNode]:
        """
        核心方法：接收 Markdown 字符串进行切片
        :param markdown_text: Router 返回的 markdown 文本
        :param metadata: 文件的元数据（如 {"source_file": "合同.pdf"}），用于后续溯源
        """
        if not markdown_text or not markdown_text.strip():
            raise EmptyDocumentError("切片输入文本为空")

        metadata = dict(metadata or {})
        tenant_id = str(metadata.get("tenant_id") or "").strip()
        document_id = str(metadata.get("document_id") or metadata.get("id") or "").strip()
        version = metadata.get("version", 1)
        if not tenant_id or not document_id:
            raise ValueError("切片必须提供 tenant_id 和 document_id")
        metadata["document_id"] = document_id
        metadata["version"] = version

        doc = Document(
            text=markdown_text,
            metadata=metadata
        )

        # 设置元数据不参与 Embedding 计算（防止文件名污染语义空间） 但在检索出结果后，展示给用户时依然可见
        doc.excluded_embed_metadata_keys = list(metadata.keys())
        # 业务元数据也不应改变 SentenceSplitter 的有效切片预算。
        doc.excluded_llm_metadata_keys = list(metadata.keys())

        logger.info(f"🔪 启动级联切片，输入文本长度: {len(markdown_text)} 字符")

        # 1. 第一刀：按 Markdown 结构 (##, ###) 智能切分
        structural_nodes = self.md_parser.get_nodes_from_documents([doc])
        logger.info(f"   ✂️ [结构切片] 生成粗粒度节点: {len(structural_nodes)} 个")

        # 2. 第二刀：对超过 chunk_size 的长文本块，在标点符号处安全截断
        final_nodes = self.text_parser.get_nodes_from_documents(structural_nodes)
        logger.info(f"   ✂️[长度切片] 生成最终安全节点: {len(final_nodes)} 个")
        if not final_nodes:
            raise EmptyDocumentError("文档未生成任何切片")

        # 确保幂等性，避免重复向量化
        for chunk_index, node in enumerate(final_nodes):
            node.metadata["document_id"] = document_id
            node.metadata["version"] = version
            node.metadata["chunk_index"] = chunk_index
            node.id_ = stable_node_id(tenant_id, document_id, version, chunk_index)

        return final_nodes




