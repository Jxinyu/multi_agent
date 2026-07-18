# PubTables-1M 公开文档解析实验

- 运行编号：`pubtables_public_50_20260707`
- 数据集：`docling-project/PubTables-1M_OTSL-v1.1` / `test` split
- 样本量：`50` 个公开测试表格
- 平均表格规模：`13.4` 行 x `5.7` 列，`55.0` 个唯一非空金标单元格
- 结果目录：`D:\学习笔记\langchain\rag_upper\evals\results\parsing\pubtables_public_50_20260707`

## 基准说明

PubTables-1M 是公开表格抽取基准，来源于科学论文表格。Microsoft Research 页面说明该数据集包含近百万张表格，并提供表头、位置等结构信息；Hugging Face 上的 OTSL v1.1 转换版本提供表格图像、cell 文本和结构标注，可用于图像表格解析与表格结构识别评估。

本实验不是 PubTables 官方排行榜评测，而是面向当前项目文档解析路由策略的项目级验证：用公开表格图像样本检测解析结果是否保留金标单元格文本。

## 对比方案

- `pymupdf_text_only_pdf`：将表格图像转为 image-only PDF 后，使用轻量文本抽取器解析。它代表常见的快速 PDF 文本路径，但无法读取扫描图像中的表格文字。
- `router_auto_pdf`：当前项目的 `DocumentParserRouter(mode="auto")`，对同一 image-only PDF 进行探测，识别为扫描件后路由到本地 OCR。
- `rapidocr_direct_image`：直接对原始表格图像使用本地 OCR，用于诊断 OCR 组件本身的上限，不作为主系统路径。

## 指标

- `cell_recall`：解析输出中能匹配到的唯一非空 PubTables 金标单元格文本比例。
- `numeric_recall`：只统计包含数字的 cell 文本召回。
- `header_recall`：根据 PubTables bounding box 选取顶部表头区域后的表头文本召回。
- `table_retention_score`：`0.60 * cell_recall + 0.25 * numeric_recall + 0.15 * header_recall`。

## 聚合结果

| 解析器 | 成功率 | 单元格召回 | 数值召回 | 表头召回 | 表格保留分数 | 平均耗时 |
|---|---:|---:|---:|---:|---:|---:|
| pymupdf_text_only_pdf | 100.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.01s |
| router_auto_pdf | 100.00% | 87.38% | 87.53% | 84.23% | 86.94% | 2.11s |
| rapidocr_direct_image | 100.00% | 90.90% | 90.43% | 82.49% | 89.52% | 2.12s |

## 主要提升

- 基线：`pymupdf_text_only_pdf` 表格保留分数 = `0.00%`
- 当前方案：`router_auto_pdf` 表格保留分数 = `86.94%`
- 绝对提升：`86.94%`
- 相对提升：`不定义`。原因是 image-only PDF 的文本抽取基线为 0，此时相对提升倍数没有实际解释意义。

## 结论

这个公开样本实验支持当前设计判断：扫描件和图像表格不能继续走纯文本 PDF 快速路径，必须路由到 OCR/VLM 类解析器。简历中建议写“PubTables-1M 50 个公开测试表格上 table retention 达到 86.94%”或“相对 image-only 文本抽取基线绝对提升 86.94pp”，不要写无限倍或相对倍数。

## 资料来源

- Microsoft Research PubTables-1M 项目：https://www.microsoft.com/en-us/research/publication/pubtables-1m/
- Hugging Face 数据集：https://huggingface.co/datasets/docling-project/PubTables-1M_OTSL-v1.1
- CVPR 2022 论文 PDF：https://openaccess.thecvf.com/content/CVPR2022/papers/Smock_PubTables-1M_Towards_Comprehensive_Table_Extraction_From_Unstructured_Documents_CVPR_2022_paper.pdf
