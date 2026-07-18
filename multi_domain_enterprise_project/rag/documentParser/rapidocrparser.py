import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path

import fitz
from rapidocr_onnxruntime import RapidOCR

from multi_domain_enterprise_project.rag.documentParser.exception_handling import DocumentParsingError

logger = logging.getLogger(__name__)


class EnterpriseRapidOCRParser:
    """本地 OCR 解析器，适用于扫描式 PDF 和表格图片。"""

    file_max_size_mb = 50
    support_file_types = [".pdf", ".png", ".jpg", ".jpeg", ".bmp"]

    def __init__(self):
        self.ocr = RapidOCR()

    def _validate_file(self, file_path: Path) -> None:
        if not file_path.exists():
            raise FileNotFoundError(f"找不到文件: {file_path}")
        if file_path.suffix.lower() not in self.support_file_types:
            raise ValueError(f"不支持的文件格式: {file_path.suffix}")
        file_size_mb = os.path.getsize(file_path) / 1024 / 1024
        if file_size_mb == 0:
            raise ValueError(f"文件 {file_path} 为空。")
        if file_size_mb > self.file_max_size_mb:
            raise ValueError(f"文件 {file_path} 超过 {self.file_max_size_mb}MB。")

    def _ocr_image(self, image_path: str) -> str:
        result, _elapsed = self.ocr(image_path)
        if not result:
            return ""
        return "\n".join(item[1] for item in result if len(item) >= 2 and item[1])

    def _parse_sync(self, file_path: str) -> str:
        path = Path(file_path)
        ext = path.suffix.lower()
        if ext != ".pdf":
            return self._ocr_image(str(path))

        chunks: list[str] = []
        with tempfile.TemporaryDirectory(prefix="rapidocr-pages-") as temp_dir:
            doc = fitz.open(str(path))
            try:
                for page_index, page in enumerate(doc):
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    image_path = Path(temp_dir) / f"page_{page_index + 1}.png"
                    pix.save(str(image_path))
                    text = self._ocr_image(str(image_path))
                    if text:
                        chunks.append(f"## Page {page_index + 1}\n{text}")
            finally:
                doc.close()
        return "\n\n".join(chunks)

    async def parse_file(self, file_path: str) -> str:
        path = Path(file_path)
        self._validate_file(path)
        start_time = time.time()
        logger.info("开始本地 OCR 解析")
        try:
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(None, self._parse_sync, file_path)
            logger.info("本地 OCR 解析完成，耗时 %.1fs", time.time() - start_time)
            return text
        except Exception as exc:
            logger.error("本地 OCR 解析失败: %s", exc)
            raise DocumentParsingError(f"本地 OCR 解析失败：{exc}") from exc
