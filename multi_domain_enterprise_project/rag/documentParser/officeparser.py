import asyncio
import logging
import os
import time
from pathlib import Path

from markitdown import MarkItDown

from multi_domain_enterprise_project.rag.documentParser.exception_handling import DocumentParsingError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class EnterpriseOfficeParser:
    """
    适用场景：.docx, .pptx, .xlsx, .html, .csv
    """

    file_max_size_mb = 50
    support_file_types = [".doc", ".docx", ".ppt", ".pptx", ".xlsx", ".xls", ".txt", ".md", ".csv", ".json", ".html"]

    def __init__(self):
        pass

    def _validate_file(self, file_path: Path):
        """
        检查文件格式是否支持
        """
        if not file_path.exists():
            raise FileNotFoundError(f"找不到文件: {file_path}")
        if file_path.suffix not in self.support_file_types:
            raise ValueError(f"不支持的文件格式: {file_path.suffix}")
        file_size_mb = os.path.getsize(file_path) / 1024 / 1024  # MB
        if file_size_mb == 0:
            raise ValueError(f"⚠️ 文件 {file_path} 为空。")
        if file_size_mb > self.file_max_size_mb:
            raise ValueError(f"⚠️ 文件 {file_path} 超过 {self.file_max_size_mb}MB。")

    async def parse_file(self, file_path: str) -> str:
        """
        解析 Office 文档，返回 LlamaIndex Document 列表。
        注意：Office 文档通常没有物理“页码”的严格概念，所以一般作为一个大 Document 返回，
        后续再由 LlamaIndex 的 MarkdownNodeParser 进行文本分块(Chunking)。
        """

        md_converter = MarkItDown()
        loop = asyncio.get_event_loop()

        path_obj = Path(file_path)
        start_time = time.time()

        self._validate_file(path_obj)

        logger.info("开始 Office 文档解析")

        try:
            # 转换为 Markdown
            result = await loop.run_in_executor(
                None,
                md_converter.convert,
                file_path
            )
            documents = result.text_content

            if not documents:
                logger.error("Office 文档解析完成但未提取到内容")
                return ''

            logger.info(
                f"🚀 解析完成: {path_obj.name} ({len(documents)} pages; "
                f"耗时: {time.time() - start_time:.1f}s)")
            return documents

        except FileNotFoundError as fe:
            logger.error("Office 文档不存在")
            raise DocumentParsingError(f"文档不存在：{str(fe)}") from fe
        except ValueError as ve:
            logger.error("Office 文档校验失败")
            raise DocumentParsingError(f"文件校验错误：{str(ve)}") from ve
        except Exception as e:
            logger.error(f"❌ 发生未知严重错误: {str(e)}")
            raise DocumentParsingError(f"文档解析过程中发生系统错误：{str(e)}") from e


async def parse_file_by_officeParse(file_path: str) -> str:
    """
    使用 OfficeParser 解析 Office 文档，
    """
    parser = EnterpriseOfficeParser()
    try:
        return await parser.parse_file(file_path)
    except DocumentParsingError as e:
        logger.error(f"❌ 文档解析错误: {str(e)}")


if __name__ == '__main__':
    res = asyncio.run(parse_file_by_officeParse(r"/document/rag中处理excel表格.txt"))
    print(res)
