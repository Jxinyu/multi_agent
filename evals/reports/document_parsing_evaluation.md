# 文档解析路由实验报告

## 结论

- 运行编号：`parsing_full_20260706_220325`
- 样本量：30 个页面级/文件级样本
- 主质量指标：`table_retention_score`
- 成本指标：云端解析调用次数
- 质量目标：auto-router 相比 local-fast-only 表格信息保留率相对提升 30%
- 成本目标：auto-router 相比 cloud-accurate-only 解析成本降低 25%
- 当前质量结论：达到 30% 相对提升
- 当前成本结论：达到 25% 成本降低
- 表格信息保留率相对提升：49.99%
- 云解析调用成本降低：100.00%

- 云端质量基线说明：`cloud_accurate_only` 在本次环境中未形成有效质量基线；30 个样本返回空结果或解析失败。日志显示当前 LlamaParse SDK/API 仍命中旧解析模式不支持错误，因此该列仅保留云端调用成本口径，不用于证明质量优于云端。

## 实验方法

本实验评估项目中的 `DocumentParserRouter(mode="auto")` 是否能在复杂文档上保留更多表格信息，并减少不必要的云端解析调用。样本为受控页面级集合，任务设计参考 PubTables-1M 的表格结构识别/单元格内容保留任务，以及 OmniDocBench 的多版面文档解析任务。金标由脚本生成，因此可以稳定计算单元格召回率。

注意：本实验不是 PubTables-1M 或 OmniDocBench 官方排行榜分数；它是面向当前项目解析路由策略的可复现实验。

### 数据集

样本类型分布：

```json
{
  "native_pdf": 10,
  "scanned_pdf": 10,
  "xlsx": 10
}
```

- `native_pdf`：原生数字 PDF，文本可直接抽取。
- `scanned_pdf`：扫描式表格 PDF，页面中只有表格图片，要求 OCR/视觉解析能力。
- `xlsx`：Office 表格文件，要求保留表头、数值和百分号。

每个样本包含：

- `expected_cells`：所有表格单元格文本。
- `expected_headers`：表头。
- `expected_numeric`：金额、数字、百分比。

### 基线

- `local_fast_only`：PDF 使用 PyMuPDF，本地 Office 使用 MarkItDown，不调用云端 OCR。
- `cloud_accurate_only`：所有样本都使用 LlamaParse，代表质量优先但成本最高的方案；本次环境中该基线因 API 兼容问题不可用。
- `auto_router`：使用项目 `DocumentParserRouter(mode="auto")`，原生 PDF/XLSX 走本地解析，扫描式 PDF 和图片走本地 RapidOCR。

### 指标

- `cell_recall`：输出中可匹配到的金标单元格比例。
- `header_recall`：输出中可匹配到的表头比例。
- `numeric_value_recall`：输出中可匹配到的数字/金额/百分比比例。
- `table_retention_score`：`0.5 * cell_recall + 0.25 * header_recall + 0.25 * numeric_value_recall`。
- `cloud_call_count`：云端解析调用次数，作为成本估算主口径。

## 结果

| 解析器 | 表格保留分数 | 单元格召回 | 表头召回 | 数值召回 | 云调用次数 | 错误数 | 平均耗时(s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| local_fast_only | 66.67% | 66.67% | 66.67% | 66.67% | 0 | 0 | 0.0313 |
| cloud_accurate_only | 0.00% | 0.00% | 0.00% | 0.00% | 30 | 30 | 2.5004 |
| auto_router | 100.00% | 100.00% | 100.00% | 100.00% | 0 | 0 | 0.5712 |

## 分类型结果

```json
{
  "local_fast_only": {
    "native_pdf": {
      "sample_count": 10,
      "cell_recall": 1.0,
      "table_retention_score": 1.0
    },
    "scanned_pdf": {
      "sample_count": 10,
      "cell_recall": 0.0,
      "table_retention_score": 0.0
    },
    "xlsx": {
      "sample_count": 10,
      "cell_recall": 1.0,
      "table_retention_score": 1.0
    }
  },
  "cloud_accurate_only": {
    "native_pdf": {
      "sample_count": 10,
      "cell_recall": 0.0,
      "table_retention_score": 0.0
    },
    "scanned_pdf": {
      "sample_count": 10,
      "cell_recall": 0.0,
      "table_retention_score": 0.0
    },
    "xlsx": {
      "sample_count": 10,
      "cell_recall": 0.0,
      "table_retention_score": 0.0
    }
  },
  "auto_router": {
    "native_pdf": {
      "sample_count": 10,
      "cell_recall": 1.0,
      "table_retention_score": 1.0
    },
    "scanned_pdf": {
      "sample_count": 10,
      "cell_recall": 1.0,
      "table_retention_score": 1.0
    },
    "xlsx": {
      "sample_count": 10,
      "cell_recall": 1.0,
      "table_retention_score": 1.0
    }
  }
}
```

## 提升率

```text
table_retention_lift = (auto_router_table_retention - local_fast_only_table_retention) / local_fast_only_table_retention
cost_reduction = (cloud_accurate_only_cloud_calls - auto_router_cloud_calls) / cloud_accurate_only_cloud_calls
```

当前结果：

- `table_retention_lift`: 49.99%
- `cost_reduction`: 100.00%

## 复现命令

```bash
conda run -n rag python evals/parsing/run_document_parsing_eval.py --sample-limit 30
```

## 输出文件

- 配置：`evals/results/parsing/parsing_full_20260706_220325/config.json`
- 原始结果：`evals/results/parsing/parsing_full_20260706_220325/raw_parsing_results.jsonl`
- 指标：`evals/results/parsing/parsing_full_20260706_220325/metrics.json`
- 样本清单：`evals/data/parsing/controlled_manifest.json`
- 本报告：`evals/reports/document_parsing_evaluation.md`

## 注意事项

- 该实验对 LlamaParse API 输出做了缓存；如果设置 `--reparse` 会再次消耗云端解析调用。
- 本次 `cloud_accurate_only` 遇到 LlamaParse 旧解析模式不支持错误，质量结果不可作为有效云端质量分数。
- 成本以云端调用次数估算，不代表真实账单金额。
- 如果后续改动 `DocumentParserRouter` 的路由策略，需要重跑本实验。

## 公开数据集补充验证：PubTables-1M

为避免只依赖自建控制样本，补充运行了 PubTables-1M OTSL v1.1 `test` split 的 50 个公开表格图像样本。该实验将表格图像转为 image-only PDF，比较固定文本抽取基线与当前文档解析路由。

- 运行编号：`pubtables_public_50_20260707`
- 样本量：50 个公开测试表格，平均 `13.4` 行 x `5.7` 列，平均 `55.0` 个唯一非空金标单元格
- 基线：`pymupdf_text_only_pdf`
- 当前方案：`router_auto_pdf`
- 诊断上限：`rapidocr_direct_image`
- 报告：`evals/reports/pubtables_document_parsing_evaluation.md`
- 结果：`evals/results/parsing/pubtables_public_50_20260707/metrics.json`
- 原始逐条结果：`evals/results/parsing/pubtables_public_50_20260707/raw_parsing_results.jsonl`

| 解析器 | 成功率 | 单元格召回 | 数值召回 | 表头召回 | 表格保留分数 | 平均耗时(s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| pymupdf_text_only_pdf | 100.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.01 |
| router_auto_pdf | 100.00% | 87.38% | 87.53% | 84.23% | 86.94% | 2.11 |
| rapidocr_direct_image | 100.00% | 90.90% | 90.43% | 82.49% | 89.52% | 2.12 |

结论：PubTables 公开样本支持“扫描/图像表格必须离开纯文本 PDF 快速路径并路由到 OCR/VLM 类解析”的设计判断。因为文本抽取基线在 image-only PDF 上为 0，简历中不建议写相对提升倍数；更稳妥写法是“在 PubTables-1M 50 个公开测试表格上，自动路由将表格信息保留分数从 0 提升到 86.94%，并在控制样本上相对 local-fast 提升 49.99%”。
