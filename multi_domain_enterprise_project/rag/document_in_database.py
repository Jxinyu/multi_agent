import asyncio
import hashlib
import logging
import re

import short_unique_id as suid

from multi_domain_enterprise_project.core.storage import parsed_document_path
from multi_domain_enterprise_project.rag.chunker import EnterpriseDocumentChunker
from multi_domain_enterprise_project.rag.documentParser.exception_handling import DocumentParsingError
from multi_domain_enterprise_project.rag.documentParser.parser_route import DocumentParserRouter
from multi_domain_enterprise_project.rag.exceptions import DualWriteError, EmptyDocumentError
from multi_domain_enterprise_project.rag.graph.ingestion_graph import get_graph_store_pipeline_service
from multi_domain_enterprise_project.rag.milvus.ingestion_milvus import get_milvus_store_pipeline_service

logger = logging.getLogger(__name__)


async def get_snowflake_id() -> str:
    """
    生成一个随机的 snowflake ID
    """
    return str(suid.get_next_snowflake_id())


async def _clean_markdown_wrapper(text: str) -> str:
    """
    清洗解析器可能附带的 ```markdown ... ``` 外套
    """
    text = text.strip()
    # 使用正则匹配，兼容 ```markdown, ```md, 或者仅有 ``` 开头的情况
    # re.DOTALL 使得 . 可以匹配换行符
    pattern = r"^```(?:markdown|md)?\s*\n(.*?)\n```$"
    match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)

    if match:
        logger.info("🧹 检测到 ```markdown 外套，已自动剥离！")
        return match.group(1).strip()

    # 兜底：如果没匹配上正则，但确实以 ``` 开头和结尾（比如没有换行的情况）
    if text.startswith("```") and text.endswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("markdown"):
            text = text[8:].strip()
        elif text.lower().startswith("md"):
            text = text[2:].strip()
        logger.info("🧹 执行了基础的 markdown 外套剥离！")
        return text

    return text


async def clean_document_str(file_path: str, tenant_id: str, document_id: str | None = None):
    """
    获取文档的md格式文本
    :param file_path: 文档的存储路径
    :param tenant_id: 文档所属的租户
    :return:
    """
    logger.info("开始处理待入库文档")
    router = DocumentParserRouter(mode="auto")
    try:
        # 获取md文本
        markdown_text = await router.route_and_parse(file_path)
        if not isinstance(markdown_text, str):
            raise DocumentParsingError("解析器未返回文本")
        # 格式化md文本
        markdown_text = await _clean_markdown_wrapper(markdown_text)
        if not markdown_text.strip():
            raise DocumentParsingError("文档解析结果为空")
        # 存储md文本
        resolved_document_id = document_id or _content_document_id(file_path, tenant_id)
        file_path_md = parsed_document_path(tenant_id, resolved_document_id)
        file_path_md.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path_md, 'w', encoding='utf-8') as f:
            f.write(markdown_text)
        return markdown_text, file_path_md
    except DocumentParsingError:
        raise
    except Exception as exc:
        logger.exception("文档解析阶段失败")
        raise DocumentParsingError("文档解析失败") from exc


def _content_document_id(file_path: str, tenant_id: str) -> str:
    digest = hashlib.sha256()
    digest.update(tenant_id.encode("utf-8"))
    digest.update(b"\0")
    with open(file_path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ensure_document_identity(metadata: dict) -> None:
    tenant_id = str(metadata.get("tenant_id") or "").strip()
    if not tenant_id:
        raise ValueError("入库必须提供 tenant_id")
    document_id = str(metadata.get("document_id") or metadata.get("id") or "").strip()
    if not document_id:
        document_id = _content_document_id(str(metadata["file_path"]), tenant_id)
    metadata["document_id"] = document_id
    metadata["version"] = metadata.get("version", 1)


async def insert_document(metadata: dict, mode: str = "milvus"):
    """
    RAG ETL 主流程：文件 -> 解析 -> 切片 -> 向量化 -> 存储
    file_path: 文件存储路径
    tenant_id: 租户id  部门
    user_id: 用户id  用户账号
    title: 文档标题
    acl: 最低访问权限
    mode: 默认是 'milvus' 表示检索向量数据库；'graph' 表示检索知识图谱; 'mg': 表示检索向量数据库+知识图谱;
    """
    _ensure_document_identity(metadata)

    # --- Step 1: 智能路由解析 获取文档的md格式---
    markdown_text, file_path_md = await clean_document_str(
        metadata["file_path"], metadata["tenant_id"], metadata["document_id"]
    )
    metadata["file_path_md"] = str(file_path_md)

    # --- Step 2: 级联切片 ---
    chunker = EnterpriseDocumentChunker(chunk_size=512, chunk_overlap=50)
    nodes = chunker.split_text(markdown_text, metadata=metadata)

    if not nodes:
        raise EmptyDocumentError("文档未生成任何切片")
    chunk_count = len(nodes)
    logger.info(f"✅ 切片完成: {chunk_count} 个节点")

    # --- Step 3: 向量化与存储 (Milvus/graph neo4j) ---
    if mode == "milvus":
        milvus_ingestion = get_milvus_store_pipeline_service()
        logger.info("开始写入 Milvus")
        await milvus_ingestion.insert_nodes(nodes)  # 插入数据
        logger.info("Milvus 入库完成")
    elif mode == "graph":
        logger.info("开始写入 Neo4j")
        graph_ingestion = get_graph_store_pipeline_service()
        await graph_ingestion.insert_nodes(nodes)
        logger.info("Neo4j 入库完成")
    elif mode == "mg":
        logger.info("开始写入 Milvus 与 Neo4j")
        # 如果是图文双路入库模式
        milvus_ingestion = get_milvus_store_pipeline_service()
        graph_ingestion = get_graph_store_pipeline_service()
        results = await asyncio.gather(
            milvus_ingestion.insert_nodes(nodes),
            graph_ingestion.insert_nodes(nodes),
            return_exceptions=True,
        )
        backend_status = {}
        for backend, result in zip(("milvus", "neo4j"), results, strict=True):
            if isinstance(result, Exception):
                backend_status[backend] = {"status": "failed", "error": str(result)}
                logger.error("%s 入库发生异常", backend)
            else:
                backend_status[backend] = {"status": "success", "error": None}
        metadata["backend_status"] = backend_status
        if any(item["status"] == "failed" for item in backend_status.values()):
            raise DualWriteError(backend_status)
        logger.info("Milvus 与 Neo4j 双路入库完成")
    else:
        raise ValueError(f"不支持的入库模式: {mode}")

    metadata["chunk_count"] = chunk_count
    return chunk_count
