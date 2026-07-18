from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import llama_cloud
from llama_cloud import AsyncLlamaCloud

from config import settings
from multi_domain_enterprise_project.rag.documentParser.exception_handling import DocumentParsingError

logger = logging.getLogger(__name__)

DEFAULT_PROMPT = (
    "Transcribe the document exactly into Markdown. Do not summarize or answer questions. "
    "Preserve headings, paragraphs, reading order, tables, numeric values and formulas."
)


class EnterpriseDocParser:
    """基于当前 Llama Cloud SDK 的高精度云文档解析器。"""

    file_max_size_mb = 50
    support_file_types = {
        ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
        ".txt", ".md", ".png", ".jpg", ".jpeg", ".svg",
    }

    def __init__(self) -> None:
        self.api_key = settings.llm_key.llamaParse

    def _validate_file(self, file_path: Path) -> None:
        if not self.api_key:
            raise DocumentParsingError("LLAMA_PARSE_API_KEY 未配置")
        if not file_path.is_file():
            raise DocumentParsingError("文档不存在")
        if file_path.suffix.lower() not in self.support_file_types:
            raise DocumentParsingError(f"不支持的文件类型: {file_path.suffix.lower()}")
        file_size_mb = os.path.getsize(file_path) / 1024 / 1024
        if file_size_mb == 0:
            raise DocumentParsingError("文档为空")
        if file_size_mb > self.file_max_size_mb:
            raise DocumentParsingError(f"文档超过 {self.file_max_size_mb} MB")

    @staticmethod
    def _markdown_from_result(result) -> str:
        if result.markdown_full:
            return result.markdown_full.strip()
        if result.markdown is None:
            return ""
        pages: list[str] = []
        failed_pages: list[int] = []
        for page in result.markdown.pages:
            if not page.success:
                failed_pages.append(page.page_number)
                continue
            pages.append(page.markdown)
        if failed_pages:
            raise DocumentParsingError("云解析存在失败页面: " + ", ".join(map(str, failed_pages)))
        return "\n\n".join(pages).strip()

    async def parse_file(self, file_path: str, instruction: str = "") -> str:
        path = Path(file_path)
        self._validate_file(path)
        started = time.perf_counter()
        try:
            async with AsyncLlamaCloud(
                api_key=self.api_key,
                max_retries=settings.llama_parser.max_retries,
            ) as client:
                result = await client.parsing.parse(
                    tier=settings.llama_parser.tier,
                    version=settings.llama_parser.version,
                    upload_file=path,
                    disable_cache=settings.llama_parser.invalidate_cache,
                    expand=["markdown"],
                    agentic_options={"custom_prompt": instruction or DEFAULT_PROMPT},
                    processing_options={"aggressive_table_extraction": True},
                    processing_control={
                        "job_failure_conditions": {
                            "allowed_page_failure_ratio": 0.01,
                            "fail_on_image_ocr_error": True,
                            "fail_on_markdown_reconstruction_error": True,
                        },
                        "timeouts": {"base_in_seconds": settings.llama_parser.timeout_seconds},
                    },
                    timeout=float(settings.llama_parser.timeout_seconds),
                )
            markdown = self._markdown_from_result(result)
            if not markdown:
                raise DocumentParsingError("云解析未返回 Markdown 内容")
            logger.info("云解析完成，耗时 %.1fs", time.perf_counter() - started)
            return markdown
        except DocumentParsingError:
            raise
        except (llama_cloud.APIConnectionError, llama_cloud.APITimeoutError) as exc:
            raise DocumentParsingError("云解析服务连接失败或超时") from exc
        except llama_cloud.APIStatusError as exc:
            raise DocumentParsingError(f"云解析服务返回 HTTP {exc.status_code}") from exc
        except Exception as exc:
            raise DocumentParsingError("云解析任务失败") from exc


async def parse_file_by_llamaParse(file_path: str) -> str:
    return await EnterpriseDocParser().parse_file(file_path)
