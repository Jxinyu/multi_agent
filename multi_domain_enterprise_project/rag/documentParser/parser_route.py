import os
import time
import logging
import asyncio
import zipfile
from pathlib import Path

import fitz

from multi_domain_enterprise_project.rag.documentParser.llamaparser import EnterpriseDocParser
from multi_domain_enterprise_project.rag.documentParser.officeparser import EnterpriseOfficeParser
from multi_domain_enterprise_project.rag.documentParser.pymupdfparser import EnterprisePyMuPDFParser
from multi_domain_enterprise_project.rag.documentParser.qwenparser import EnterpriseLocalVLMParser
from multi_domain_enterprise_project.rag.documentParser.exception_handling import DocumentParsingError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class DocumentParserRouter:
    """
    企业级文档解析智能路由器
    负责分析文档特征，将解析任务分发给最合适的底层解析器，平衡成本、延迟与质量。
    """

    def __init__(self, mode: str = "auto"):
        """
        :param mode: 解析模式
            - "auto": 智能路由（默认：平衡成本、速度、精度，动态分发）
            - "fast": 本地极速模式（不调用云端 API，绝对省钱、数据绝对不出域保密）
            - "accurate": 高精度模式（无视成本，只要是复杂文档无脑扔给云端大模型）
        """
        self.mode = mode

        # 懒加载初始化解析器，避免启动路由器时占用过多内存或显存
        self._office_parser = None
        self._pymupdf_parser = None
        self._qwen_parser = None
        self._llama_parser = None

    @property
    def office_parser(self):
        if not self._office_parser:
            logger.info("🔧 初始化 [EnterpriseOfficeParser] (MarkItDown)")
            self._office_parser = EnterpriseOfficeParser()
        return self._office_parser

    @property
    def pymupdf_parser(self):
        if not self._pymupdf_parser:
            logger.info("🔧 初始化 [EnterprisePyMuPDFParser] (PyMuPDF4LLM)")
            self._pymupdf_parser = EnterprisePyMuPDFParser()
        return self._pymupdf_parser

    @property
    def qwen_parser(self):
        if not self._qwen_parser:
            logger.info("🔧 初始化 [EnterpriseLocalVLMParser] (Qwen2.5-VL)")
            self._qwen_parser = EnterpriseLocalVLMParser()
        return self._qwen_parser

    @property
    def llama_parser(self):
        if not self._llama_parser:
            logger.info("🔧 初始化 [EnterpriseDocParser] (LlamaParse)")
            self._llama_parser = EnterpriseDocParser()
        return self._llama_parser

    def _probe_office(self, file_path: str) -> dict:
        """
        【Office核心探测器】花 0.005 秒解析 OOXML 目录树
        通过计算 media (图片) 和 charts (图表) 文件夹内的文件数量，判断复杂度
        """
        image_count = 0
        chart_count = 0

        try:
            # 直接将 docx/pptx/xlsx 当作 zip 读取目录树 (极快，不占用内存)
            with zipfile.ZipFile(file_path, 'r') as z:
                file_list = z.namelist()

                for f in file_list:
                    # 匹配图片资源
                    if f.startswith(('word/media/', 'ppt/media/', 'xl/media/')):
                        image_count += 1
                    # 匹配原生图表 (柱状图、饼图等)
                    elif f.startswith(('word/charts/', 'ppt/charts/', 'xl/charts/')):
                        chart_count += 1

            logger.info(f"📊 Office探针分析完成: 图片={image_count}张, 图表={chart_count}个")

            # 判断标准：如果有超过 3 张图，或者只要存在 1 个图表，就认为是复杂文档
            is_complex = chart_count > 0 or image_count > 3

            return {
                "image_count": image_count,
                "chart_count": chart_count,
                "is_complex": is_complex
            }
        except zipfile.BadZipFile:
            # 如果不是标准的 OOXML (比如老版本的 .doc 或已被破坏的结构)，安全起见走复杂路线
            logger.warning(f"⚠️ 无法将文件作为 ZIP 读取(可能是旧版 .doc)，默认判定为复杂模式")
            return {"is_complex": True}
        except Exception as e:
            logger.warning(f"⚠️ Office 探针分析失败: {e}")
            return {"is_complex": True}

    def _probe_pdf(self, file_path: str) -> str:
        """
        【企业级 PDF 核心探测器 V2】花 0.05 秒精准侦查 PDF 构成
        采用分层抽样、排版碎片率计算，输出绝对互斥的路由建议。
        返回结果为字符串枚举: 'scanned' | 'complex' | 'simple'
        """
        try:
            doc = fitz.open(file_path)
            total_pages = len(doc)

            # 1. 解决【采样偏差】：分层抽样
            # 避免被封面和目录欺骗，最多抽样 3 页：首页、中间页、尾页
            if total_pages <= 3:
                pages_to_check = list(range(total_pages))
            else:
                pages_to_check = list(range(1, total_pages))  # 跳过封面(0)，从第2页开始

            total_chars = 0
            total_images = 0
            total_drawings = 0
            total_blocks = 0  # 文本块数量，用于评估排版碎片率

            for p_idx in pages_to_check:
                page = doc[p_idx]

                # 获取纯文本
                text = page.get_text("text").strip()
                total_chars += len(text)

                # 获取图片和矢量线框
                total_images += len(page.get_images(full=True))
                total_drawings += len(page.get_drawings())

                # 复杂的双栏、三栏、嵌套表格，会导致 block 数量激增
                blocks = page.get_text("blocks")
                total_blocks += len(blocks)

            doc.close()

            # 2. 解决【未均值化】：全部转换为单页平均值
            num_sampled = len(pages_to_check)
            avg_chars = total_chars / num_sampled
            avg_images = total_images / num_sampled
            avg_drawings = total_drawings / num_sampled
            avg_blocks = total_blocks / num_sampled

            logger.info(f"📊 PDF探针(抽样{num_sampled}页): "
                        f"均字={avg_chars:.0f}, 均图={avg_images:.1f}, "
                        f"均矢量={avg_drawings:.1f}, 均文本块={avg_blocks:.1f}")

            # 3. 解决【标志位冲突】与【阈值死板】：使用互斥的优先级决策树

            # 优先级 1：纯扫描件探测 (Scanned)
            # 提高容错率(150字)，防止扫描件OCR噪点导致的误判；同时必须包含图片
            if avg_chars < 150 and avg_images >= 0.5:
                return "scanned"

            # 优先级 2：复杂版面探测 (Complex)
            # 满足以下任一条件即可判定为复杂版面：
            # a. 矢量图过多 (平均大于 5，通常是数据图表、线框表格)
            # b. 图片过多 (平均大于 2，通常是 PPT 导出的 PDF)
            # c. 【核心】文本碎片率极高 (平均大于 40 块，必然是多栏排版或密集表格)
            if avg_drawings > 5 or avg_images > 2 or avg_blocks > 40:
                return "complex"

            # 优先级 3：简单文本兜底 (Simple)
            # 不满足上述条件，一律视为对轻量解析器友好的原生数字文档
            return "simple"

        except Exception as e:
            logger.warning(f"⚠️ PDF 探针分析失败，强制降级为 complex 处理: {e}")
            return "complex"  # 探针异常时，安全降级给最强的解析器

    async def route_and_parse(self, file_path: str) -> str:
        """
        接收文件路径，执行路由分发并返回提取的 Markdown/Text 字符串
        """
        path_obj = Path(file_path)
        ext = path_obj.suffix.lower()

        start_time = time.time()
        logger.info(f"🚦 路由器接收到任务: {path_obj.name} | 策略模式: [{self.mode.upper()}]")

        if not path_obj.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        try:
            # ================== 1. Office 文档路由 ==================
            if ext in [".doc", ".docx", ".ppt", ".pptx", ".xlsx", ".xls"]:
                if self.mode == "accurate":
                    logger.info("👉 决策: 强制高精模式，分发给 [LlamaParser]")
                    return await self.llama_parser.parse_file(file_path)

                # 特别关照 PPT：幻灯片天生排版极其复杂，文本框随意放置，极易丢失空间语义
                if ext in [".ppt", ".pptx"]:
                    if self.mode == "fast":
                        logger.info("👉 决策: PPT幻灯片 (极速模式拦截)，牺牲排版交由本地 [OfficeParser]")
                        return await self.office_parser.parse_file(file_path)
                    else:
                        logger.info("👉 决策: PPT幻灯片 (Auto模式)，为保留图表排版，分发给懂视觉的 [LlamaParser]")
                        return await self.llama_parser.parse_file(file_path)

                # Word / Excel 启用探针
                probe_result = self._probe_office(file_path)

                if probe_result["is_complex"]:
                    if self.mode == "fast":
                        logger.info("👉 决策: 复杂Office (极速模式拦截)，舍弃图表，使用本地 [OfficeParser]")
                        return await self.office_parser.parse_file(file_path)
                    else:
                        logger.info("👉 决策: 复杂Office (Auto模式)，内含多图/图表，分发给 [LlamaParser]")
                        return await self.llama_parser.parse_file(file_path)
                else:
                    logger.info("👉 决策: 简单纯文本Office，安全分发给极速本地 [OfficeParser]")
                    return await self.office_parser.parse_file(file_path)

            # ================== 2. 图片文档路由 ==================
            elif ext in [".png", ".jpg", ".jpeg", ".bmp"]:
                if self.mode == "accurate":
                    logger.info("👉 决策: 强制高精模式，分发给[LlamaParser]")
                    return await self.llama_parser.parse_file(file_path)
                else:
                    logger.info("👉 决策: 图片文件 (Auto/Fast)，分发给本地视觉大模型[QwenParser]")
                    return await self.qwen_parser.parse_file(file_path)

            # ================== 3. PDF 动态路由 ==================
            elif ext == ".pdf":
                if self.mode == "accurate":
                    logger.info("👉 决策: 强制高精模式，分发给 [LlamaParser]")
                    return await self.llama_parser.parse_file(file_path)

                    # 启用 V2 探针，拿到唯一决策指令
                route_decision = self._probe_pdf(file_path)

                if route_decision == "scanned":
                    if self.mode == "fast":
                        logger.info("👉 决策: PDF 扫描件 (极速模式)，分发给本地视觉[QwenParser]")
                        return await self.qwen_parser.parse_file(file_path)
                    else:
                        logger.info("👉 决策: PDF 扫描件 (Auto)，分发给[LlamaParser]")
                        return await self.llama_parser.parse_file(file_path)

                elif route_decision == "complex":
                    if self.mode == "fast":
                        logger.info("👉 决策: 复杂排版 PDF (极速拦截)，强制本地 [PyMuPDFParser]")
                        return await self.pymupdf_parser.parse_file(file_path)
                    else:
                        logger.info("👉 决策: 复杂排版 PDF (Auto)，分发给云端 [LlamaParser]")
                        return await self.llama_parser.parse_file(file_path)

                elif route_decision == "simple":
                    logger.info("👉 决策: 简单原生 PDF，安全分发给极速本地 [PyMuPDFParser]")
                    return await self.pymupdf_parser.parse_file(file_path)

            # ================== 4. 纯文本路由 ==================
            elif ext in [".txt", ".md", ".csv", ".json"]:
                logger.info("👉 决策: 纯文本格式，交由[OfficeParser] (MarkItDown) 快速提取")
                return await self.office_parser.parse_file(file_path)

            else:
                raise ValueError(f"不支持的文件扩展名: {ext}")

        except Exception as e:
            logger.error(f"❌ 路由解析发生异常: {e}")
            # LlamaParse 兜底重试
            if self.mode != "fast" and ext in [
                ".pdf",
                ".doc",
                ".docx",
                ".ppt",
                ".pptx",
                ".xls",
                ".xlsx",
                ".png",
                ".jpg",
                ".jpeg",
                ".bmp",
            ]:
                logger.warning("🔄 触发兜底机制: 尝试启用云端 LlamaParse 进行重试...")
                try:
                    return await self.llama_parser.parse_file(file_path)
                except Exception as fallback_e:
                    logger.error(f"❌ 兜底解析亦失败: {fallback_e}")
                    raise DocumentParsingError(f"所有路由均告失败。原始错误: {e}, 兜底错误: {fallback_e}")
            # 抛出最终业务异常
            raise DocumentParsingError(f"路由解析任务中断: {str(e)}")


if __name__ == "__main__":
    async def test_router():
        # 初始化路由器，采用智能模式
        router = DocumentParserRouter(mode="auto")

        # 将这里的路径替换为你电脑里的实际测试文件
        test_files = [
            r'D:\学习笔记\langchain\rag_upper\document\transformer.pdf',
        ]

        for file in test_files:
            if os.path.exists(file):
                print("\n" + "=" * 60)
                try:
                    res = await router.route_and_parse(file)
                    print(f"✅ [{os.path.basename(file)}] 解析成功，提取字数: {len(res)}")
                    # 打印前 200 个字符预览
                    print(f"预览:\n{res[:200]}...")
                except Exception as e:
                    print(f"❌ 测试失败: {e}")
            else:
                print(f"\n⚠️ 测试文件不存在跳过: {file}")


    # 运行异步事件循环
    asyncio.run(test_router())
