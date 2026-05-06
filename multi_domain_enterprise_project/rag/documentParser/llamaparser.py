import os
import time
from pathlib import Path

import nest_asyncio
import logging

from llama_parse import LlamaParse
from llama_index.core.schema import Document
from config import settings
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from docx2pdf import convert

from multi_domain_enterprise_project.rag.documentParser.exception_handling import DocumentParsingError

nest_asyncio.apply()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)  # 创建日志记录器


class EnterpriseDocParser:
    """
    基于 LlamaParse 最新引擎的企业级文档解析服务
    """
    file_max_size_mb = 50
    support_file_types = [
        ".pdf",
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        ".xls",
        ".xlsx",
        ".txt",
        ".md",
        ".png",
        ".jpg",
        ".jpeg",
        ".svg",
    ]

    def __init__(self):
        self.api_key = settings.llm_key.llamaParse
        if not self.api_key:
            logger.error("⚠️ 请在 config/config.yaml 中配置 LlamaParse API Key")

    def _validate_file(self, file_path: Path):
        """文件校验"""
        if not file_path.exists():
            raise FileNotFoundError(f"⚠️ 找不到文件 {file_path}。")  # 抛出文件不存在异常

        if file_path.suffix.lower() not in self.support_file_types:
            raise ValueError(f"⚠️ 不支持的文件类型 {file_path.suffix}。")  # 抛出文件类型不支持异常

        file_size_mb = os.path.getsize(file_path) / 1024 / 1024  # MB
        if file_size_mb == 0:
            raise ValueError(f"⚠️ 文件 {file_path} 为空。")  # 抛出文件为空异常
        elif file_size_mb > self.file_max_size_mb:
            raise ValueError(f"⚠️ 文件 {file_path} 超过 {self.file_max_size_mb}MB。")  # 抛出文件过大异常

        logger.info(f"文件检验通过: {file_path} ({file_size_mb:.2f} MB)")

    def _build_parser(self, mode: str = "markdown") -> LlamaParse:
        """
        工厂方法：根据需求配置 LlamaParse 实例
        :param mode: "markdown" (RAG标准) 或 "text" 或 "json" (高阶提取)
        """
        return LlamaParse(
            api_key=self.api_key,
            result_type=mode,  # 输出格式

            auto_mode=True,  # 系统自动判断使用哪个解析引擎
            auto_mode_trigger_on_image_in_page=True,  # 页面有图片时，自动升级
            auto_mode_trigger_on_table_in_page=True,  # 页面有表格时，自动升级

            continuous_mode=True,  # 针对超长文档，防止中间解析中断，自动处理分片逻辑
            high_res_ocr=True,  # 针对图表使用高精度OCR

            num_workers=4,  # 并发控制

            job_timeout_in_seconds=3 * 60,  # 超时设置，防止任务卡死

            page_error_tolerance=0.1,  # 单页错误容忍度，超过阈值则跳过
            replace_failed_page_mode="raw_text",  # 失败的页面自动降级为只提取底层原始文本 (Raw Text)

            # [调试] 生产环境设为 False，开发环境设为 True 可避免重复消耗 Credit
            invalidate_cache=settings.llama_parser.invalidate_cache,

            language="en",  # 语言
        )

    @retry(
        stop=stop_after_attempt(2),  # 最多尝试 2 次
        wait=wait_exponential(multiplier=2, min=4, max=20),  # 等待 4-20 秒 重试
        retry=retry_if_exception_type((TimeoutError, ConnectionError)),  # 错误类型
        reraise=True  # 抛出异常
    )
    async def _execute_parsing(self, parser: LlamaParse, file_path: str) -> list[Document]:
        """执行API调用，隔离网络重试逻辑"""
        return await parser.aload_data(file_path)

    async def parse_file(self, file_path: str, instruction: str = "") -> str:
        """
        执行解析任务，支持指令注入
        """
        start_time = time.time()
        path_obj = Path(file_path)

        # if path_obj.suffix != ".pdf":
        #     convert(file_path, r"D:\学习笔记\langchain\rag_upper\document\convert\output.pdf")
        #     file_path = r"D:\学习笔记\langchain\rag_upper\document\convert\output.pdf"

        try:
            self._validate_file(path_obj)  # 文件校验
            logger.info(f"🚀 开始解析任务: {path_obj.name}[Trace ID: {id(self)}]")

            parser = self._build_parser()
            # 指令注入 像 Prompt 一样控制解析行为，这是 V2 最强大的地方
            if instruction:
                parser.system_prompt = instruction
            else:
                parser.system_prompt = (
                    "You are a highly accurate academic document transcription engine. "
                    "Your ONLY task is to transcribe the document exactly as it appears into Markdown format. "
                    "RULES: "
                    "1. DO NOT summarize, extract, or answer questions. "
                    "2. Preserve all paragraphs, headings, and reading order perfectly. "
                    "3. For tables, preserve the exact row and column structure using standard Markdown table syntax. "
                    "4. Convert all mathematical equations and formulas into LaTeX format (e.g., $E=mc^2$ or $$...$$)."
                )
            # 调用API进行解析
            docs = await self._execute_parsing(parser, file_path)

            documents = "\n\n".join([doc.text for doc in docs])

            if not documents:
                logger.error(f"⚠️ 解析完成，但是没有提取到任何内容: {path_obj.name}")
                return []
            logger.info(
                f"🚀 解析完成: {path_obj.name} ({len(docs)} pages; "
                f"耗时: {time.time() - start_time:.1f}s)")
            return documents
        except FileNotFoundError as fe:
            logger.error(f"⚠️ 文件 {path_obj.name} 不存在: {fe}")
            raise DocumentParsingError(f"文档不存在：{str(fe)}") from fe
        except ValueError as ve:
            logger.error(f"⚠️ 文件 {path_obj.name} 检验错误: {ve}")
            raise DocumentParsingError(f"文件校验错误：{str(ve)}") from ve
        except (TimeoutError, ConnectionError) as ne:
            logger.error(f"❌ 网络/API 终态超时: {str(ne)} | 耗时: {time.time() - start_time:.1f}s")
            raise DocumentParsingError("文档解析服务当前不可用，请稍后再试") from ne
        except Exception as e:
            logger.error(f"❌ 发生未知严重错误: {str(e)}")
            raise DocumentParsingError(f"文档解析过程中发生系统错误：{str(e)}") from e


async def parse_file_by_llamaParse(file_path: str):
    """
    使用llamaparse解析文档
    :param file_path:
    :return:
    """
    parser_service = EnterpriseDocParser()
    try:
        return await parser_service.parse_file(file_path)
    except DocumentParsingError as e:
        logger.error(f"❌ 文档解析错误: {str(e)}")


def word_to_pdf(word_file_path: str, pdf_file_path: str):
    """word文档转为PDF"""
    convert(word_file_path, pdf_file_path)
