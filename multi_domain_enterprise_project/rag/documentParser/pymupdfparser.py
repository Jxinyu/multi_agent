import asyncio
import os
import time

import logging
from pathlib import Path
from multi_domain_enterprise_project.rag.documentParser.exception_handling import DocumentParsingError
from langchain_pymupdf4llm import PyMuPDF4LLMLoader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class EnterprisePyMuPDFParser:
    """
    企业级轻量级 PDF 解析器 (基于 PyMuPDF)
    适用场景：纯数字原生 PDF、合同、规章制度、无复杂表格的论文
    """

    file_max_size_mb = 50
    support_file_types = [".pdf"]

    def __init__(self):
        pass

    def _validate_file(self, file_path: Path):
        """
        检查文件格式是否支持
        """
        if not file_path.exists():
            raise FileNotFoundError(f"找不到文件: {file_path}")
        if not file_path.suffix in self.support_file_types:
            raise ValueError(f"不支持的文件格式: {file_path.suffix}")
        file_size_mb = os.path.getsize(file_path) / 1024 / 1024  # MB
        if file_size_mb == 0:
            raise ValueError(f"⚠️ 文件 {file_path} 为空。")
        if file_size_mb > self.file_max_size_mb:
            raise ValueError(f"⚠️ 文件 {file_path} 超过 {self.file_max_size_mb}MB。")

    async def parse_file(self, file_path: str) -> str:
        """
        解析原生 PDF，按页返回 Document 列表
        """
        path_obj = Path(file_path)
        start_time = time.time()

        self._validate_file(path_obj)

        logger.info(f"🚀 开始解析任务: {path_obj.name}[Trace ID: {id(self)}]")

        try:
            document_parser = PyMuPDF4LLMLoader(path_obj)
            documents = await document_parser.aload()

            if not documents:
                logger.error(f"⚠️ 解析完成，但是没有提取到任何内容: {path_obj.name}")
                return ''

            docs = "\n".join([doc.page_content for doc in documents])

            logger.info(
                f"🚀 解析完成: {path_obj.name} ({len(documents)} pages; "
                f"耗时: {time.time() - start_time:.1f}s)")
            return docs
        except FileNotFoundError as fe:
            logger.error(f"⚠️ 文件 {path_obj.name} 不存在: {fe}")
            raise DocumentParsingError(f"文档不存在：{str(fe)}") from fe
        except ValueError as ve:
            logger.error(f"⚠️ 文件 {path_obj.name} 检验错误: {ve}")
            raise DocumentParsingError(f"文件校验错误：{str(ve)}") from ve
        except Exception as e:
            logger.error(f"❌ 发生未知严重错误: {str(e)}")
            raise DocumentParsingError(f"文档解析过程中发生系统错误：{str(e)}") from e


async def parse_file_by_pymupdf(file_path: str) -> str:
    """
    使用pymupdf解析 PDF
    """
    parser = EnterprisePyMuPDFParser()
    try:
        return await parser.parse_file(file_path)
    except DocumentParsingError as e:
        logger.error(f"❌ 文档解析错误: {str(e)}")


if __name__ == '__main__':
    res = asyncio.run(parse_file_by_pymupdf(r'/document/transformer.pdf'))
    print(res)



