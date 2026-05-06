import os
import time
import logging
import asyncio
from pathlib import Path
from typing import Union

import ollama
from config import settings
from multi_domain_enterprise_project.rag.documentParser.exception_handling import DocumentParsingError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class EnterpriseLocalVLMParser:
    """
    企业级本地视觉大模型解析器 (基于 Ollama + Qwen2.5-VL)
    适用场景：复杂的本地表格、带格式的文档、简单的多模态理解
    """

    file_max_size_mb = 50
    support_file_types = [".png", ".jpg", ".jpeg", ".bmp", ".pdf"]

    def __init__(self, model_name: str = settings.ollama.vlm_model):
        self.model_name = model_name
        self.client = ollama.Client(host=settings.ollama.base_url)
        # 测试连接
        try:
            self.client.list()
            logger.info(f"✅ 已连接到本地 Ollama，使用模型: {self.model_name}")
        except Exception as e:
            logger.error("❌ 无法连接到 Ollama，请确保 Ollama 服务已启动。")
            raise ConnectionError("Ollama 服务未响应") from e

    def _validate_file(self, file_path: Path):
        if not file_path.exists():
            raise FileNotFoundError(f"找不到文件: {file_path}")
        if not file_path.suffix in self.support_file_types:
            raise ValueError(f"不支持的文件格式: {file_path.suffix}")
        file_size_mb = os.path.getsize(file_path) / 1024 / 1024  # MB
        if file_size_mb == 0:
            raise ValueError(f"⚠️ 文件 {file_path} 为空。")
        if file_size_mb > self.file_max_size_mb:
            raise ValueError(f"⚠️ 文件 {file_path} 超过 {self.file_max_size_mb}MB。")

    def _process_single_image(self, image_input: Union[str, bytes]) -> str:
        """调用 Ollama 进行单图推理"""
        ocr_prompt = (
            "必须使用中文回答。"
            "先概括图片的组成，再详细描述图片中的每个组成部分。"
        )

        try:
            response = self.client.chat(
                model=self.model_name,
                messages=[{
                    'role': 'user',
                    'content': ocr_prompt,
                    'images': [image_input]
                }]
            )
            return response.message.content
        except Exception as e:
            logger.error(f"Ollama 推理失败: {e}")
            return ""

    async def parse_file(self, file_path: str) -> str:
        """执行解析"""
        path_obj = Path(file_path)
        self._validate_file(path_obj)

        start_time = time.time()
        logger.info(f"🤖 开始 Qwen2.5-VL 本地解析: {path_obj.name}")

        loop = asyncio.get_event_loop()
        extracted_results = []

        try:
            content = await loop.run_in_executor(
                None, self._process_single_image, str(path_obj)
            )
            extracted_results.append(content)

            full_text = "\n\n".join(extracted_results)

            logger.info(f"✅ 解析完成: {path_obj.name} (耗时: {time.time() - start_time:.1f}s)")
            return full_text

        except FileNotFoundError as fe:
            logger.error(f"⚠️ 文件 {path_obj.name} 不存在: {fe}")
            raise DocumentParsingError(f"文档不存在：{str(fe)}") from fe
        except ValueError as ve:
            logger.error(f"⚠️ 文件 {path_obj.name} 检验错误: {ve}")
            raise DocumentParsingError(f"文件校验错误：{str(ve)}") from ve
        except Exception as e:
            logger.error(f"❌ 发生未知严重错误: {str(e)}")
            raise DocumentParsingError(f"文档解析过程中发生系统错误：{str(e)}") from e


async def parse_file_by_qwen2_5_vl(file_path: str) -> str:
    """
    使用 Qwen2.5-VL 进行本地解析
    """
    parser_service = EnterpriseLocalVLMParser()
    try:
        return await parser_service.parse_file(file_path)
    except DocumentParsingError as e:
        logger.error(f"❌ 文档解析错误: {str(e)}")


if __name__ == "__main__":
    res = asyncio.run(parse_file_by_qwen2_5_vl(r'/document/transformer.png'))
    print(res)
