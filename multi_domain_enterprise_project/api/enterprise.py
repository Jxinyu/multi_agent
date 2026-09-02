from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from multi_domain_enterprise_project.core.audit import list_audit_events
from multi_domain_enterprise_project.core.auth import CurrentUser, require_permissions
from multi_domain_enterprise_project.core.database import get_session, list_documents
from multi_domain_enterprise_project.core.sub_agent_enum import SubAgentEnum

router = APIRouter(prefix="/api/enterprise", tags=["enterprise"])
REPO_ROOT = Path(__file__).resolve().parents[2]
Session = Annotated[AsyncSession, Depends(get_session)]
EnterpriseReader = Annotated[CurrentUser, Depends(require_permissions("audit:read", "kb:read"))]

EVALUATION_PATHS = {
    "routing_full_singlelabel_20260706_210622":
        "evals/results/routing/routing_full_singlelabel_20260706_210622/metrics.json",
    "rag_lambdamart_enriched_train1300_dev200_20260707":
        "evals/results/rag/rag_lambdamart_enriched_train1300_dev200_20260707/metrics.json",
    "parsing_full_20260706_220325":
        "evals/results/parsing/parsing_full_20260706_220325/metrics.json",
    "pubtables_public_50_20260707":
        "evals/results/parsing/pubtables_public_50_20260707/metrics.json",
}

AGENT_CATALOG = {
    "finance": {
        "label": "财务智能体",
        "source_module": "multi_domain_enterprise_project.agent.finance_agent.finance_agent",
        "connection_ids": ["rag", "finance"],
        "capabilities": ["差旅与报销制度检索", "预算和采购流程问答", "财务数据可视化（按配置启用）"],
        "guardrails": ["必须先读取文档目录再检索正文", "禁止推测额度与财务规则", "每条规则必须附带引用"],
    },
    "tech": {
        "label": "技术智能体",
        "source_module": "multi_domain_enterprise_project.agent.tech_agent.tech_agent_node",
        "connection_ids": ["rag", "web"],
        "capabilities": ["内部 API 与架构文档检索", "代码规范与项目知识问答", "外部技术搜索（按配置启用）"],
        "guardrails": ["内部问题必须检索企业知识库", "外部资料必须标注来源", "资料不足时明确拒绝猜测"],
    },
    "legal": {
        "label": "法务智能体",
        "source_module": "multi_domain_enterprise_project.agent.legal_agent.legal_agent",
        "connection_ids": ["rag", "legal"],
        "capabilities": ["合同与保密协议检索", "数据保护制度问答", "法务知识服务（按配置启用）"],
        "guardrails": ["仅根据检索正文解释条款", "信息不足时升级人工法务", "回答必须包含法律意见免责声明"],
    },
    "hr": {
        "label": "HR 智能体",
        "source_module": "multi_domain_enterprise_project.agent.hr_agent.hr_agent",
        "connection_ids": ["rag"],
        "capabilities": ["员工手册与考勤制度检索", "休假和福利政策问答", "入离职流程说明"],
        "guardrails": ["回答前选择并检索相关制度", "只依据知识库结果回答", "资料不足时建议联系 HRBP"],
    },
}


class EnterpriseOverview(BaseModel):
    observed_actors: list[str]
    conversation_count: int
    completed_count: int
    failed_count: int
    waiting_count: int
    running_count: int
    document_count: int
    healthy_document_count: int
    search_count: int
    average_search_ms: int | None
    recent_events: list[dict[str, Any]]
    data_window: str = "最近 200 条租户审计事件"


class RuntimeAgent(BaseModel):
    id: str
    description: str


class RuntimeConnection(BaseModel):
    id: str
    label: str
    configured: bool


class RuntimeSummary(BaseModel):
    agents: list[RuntimeAgent]
    connections: list[RuntimeConnection]
    pipeline: list[str] = Field(default_factory=list)


class RuntimeAgentDetail(BaseModel):
    id: str
    label: str
    description: str
    source_module: str
    model_provider: str = "阿里云百炼"
    model_name: str = "qwen-plus"
    output_schema: str = "SubAgentOutputFormat"
    tool_call_limit: int = 4
    summarization_trigger_messages: int = 8
    summarization_keep_messages: int = 4
    capabilities: list[str]
    guardrails: list[str]
    connections: list[RuntimeConnection]
    editable: bool = False


class EvaluationMetric(BaseModel):
    id: str
    label: str
    baseline: float
    current: float
    unit: str
    sample_count: int
    source: str
    run_id: str


class EvaluationSummary(BaseModel):
    metrics: list[EvaluationMetric]


class EvaluationRunValue(BaseModel):
    id: str
    label: str
    value: float
    unit: str


class EvaluationRunVariant(BaseModel):
    id: str
    label: str
    role: str
    values: list[EvaluationRunValue]


class EvaluationRunDetail(BaseModel):
    run_id: str
    title: str
    category: str
    dataset: str
    split: str
    sample_count: int
    source: str
    variants: list[EvaluationRunVariant]
    notes: list[str]


def _load_json(relative_path: str) -> dict[str, Any]:
    path = (REPO_ROOT / relative_path).resolve()
    if not path.is_relative_to(REPO_ROOT) or not path.is_file():
        raise RuntimeError(f"评测结果文件不存在: {relative_path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_event_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _runtime_connections() -> list[RuntimeConnection]:
    return [
        RuntimeConnection(id="rag", label="企业 RAG MCP", configured=bool(settings.mcp.rag_url)),
        RuntimeConnection(id="web", label="网络搜索 MCP", configured=bool(settings.mcp.web_search_url)),
        RuntimeConnection(id="finance", label="财务图表 MCP", configured=bool(settings.mcp.finance_chart_url)),
        RuntimeConnection(id="legal", label="法务 MCP", configured=bool(settings.mcp.legal_url)),
    ]


def _value(data: dict[str, Any], path: tuple[str, ...]) -> float:
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            raise RuntimeError(f"评测结果缺少字段: {'.'.join(path)}")
        current = current[key]
    if not isinstance(current, int | float):
        raise RuntimeError(f"评测字段不是数值: {'.'.join(path)}")
    return float(current)


def _variant(
    data: dict[str, Any], *, variant_id: str, label: str, role: str,
    root: tuple[str, ...], metrics: list[tuple[str, str, str, tuple[str, ...]]],
) -> EvaluationRunVariant:
    return EvaluationRunVariant(
        id=variant_id,
        label=label,
        role=role,
        values=[
            EvaluationRunValue(id=metric_id, label=metric_label, unit=unit, value=_value(data, root + path))
            for metric_id, metric_label, unit, path in metrics
        ],
    )


def _evaluation_run_detail(run_id: str) -> EvaluationRunDetail:
    source = EVALUATION_PATHS.get(run_id)
    if source is None:
        raise HTTPException(status_code=404, detail="评测运行不存在")
    data = _load_json(source)

    ratio_metrics = [
        ("recall_at_5", "Recall@5", "ratio", ("recall_at_5",)),
        ("recall_at_10", "Recall@10", "ratio", ("recall_at_10",)),
        ("hit_at_10", "Hit@10", "ratio", ("hit_at_10",)),
        ("mrr_at_10", "MRR@10", "ratio", ("mrr_at_10",)),
        ("ndcg_at_10", "NDCG@10", "ratio", ("ndcg_at_10",)),
    ]
    parsing_metrics = [
        ("table_retention_score", "表格保留率", "ratio", ("table_retention_score",)),
        ("cell_recall", "单元格召回", "ratio", ("cell_recall",)),
        ("header_recall", "表头召回", "ratio", ("header_recall",)),
        ("numeric_value_recall", "数值召回", "ratio", ("numeric_value_recall",)),
        ("avg_latency_seconds", "平均延迟", "seconds", ("avg_latency_seconds",)),
        ("cloud_call_count", "云解析调用", "count", ("cloud_call_count",)),
        ("error_count", "错误数", "count", ("error_count",)),
    ]

    if run_id.startswith("routing_"):
        metrics = [
            ("enterprise_accuracy", "企业集准确率", "ratio", ("source_accuracy", "enterprise_curated")),
            ("route_accuracy", "全量路由准确率", "ratio", ("route_accuracy",)),
            ("macro_f1", "Macro F1", "ratio", ("macro_f1",)),
            ("clarification_accuracy", "追问准确率", "ratio", ("clarification_accuracy",)),
            ("multi_domain_f1", "多领域 F1", "ratio", ("multi_domain_f1",)),
            ("p95_latency_seconds", "P95 延迟", "seconds", ("p95_latency_seconds",)),
        ]
        specs = [("keyword_router", "关键词路由", "对照"), ("single_llm_router", "单 LLM 路由", "基线"),
                 ("langgraph_supervisor", "LangGraph Supervisor", "当前方案")]
        variants = [_variant(data, variant_id=item, label=label, role=role, root=("metrics", item), metrics=metrics)
                    for item, label, role in specs]
        return EvaluationRunDetail(
            run_id=run_id, title="企业多领域路由评测", category="意图路由", dataset="CLINC150 + 企业标注集",
            split="全量单标签与多领域集合", sample_count=320, source=source, variants=variants,
            notes=["简历口径使用企业标注集 120 条，避免由公开通用意图数据稀释企业场景表现。",
                   "同一输入集分别运行关键词、单 LLM 与 LangGraph Supervisor，指标由固定脚本汇总。"],
        )
    if run_id.startswith("rag_"):
        specs = [("vector_only", "仅向量检索", "基线"), ("bm25_only", "仅 BM25", "对照"),
                 ("chunk_vector", "切片向量", "对照"), ("lambdamart", "LambdaMART", "候选"),
                 ("lambdamart_source_coverage", "LambdaMART + 来源覆盖", "当前方案")]
        variants = [_variant(data, variant_id=item, label=label, role=role, root=("holdout", item), metrics=ratio_metrics)
                    for item, label, role in specs]
        return EvaluationRunDetail(
            run_id=run_id, title="多跳混合检索留出集评测", category="RAG 检索",
            dataset="公开多跳问答集的统一文档与查询构建集", split="独立 Holdout", sample_count=755,
            source=source, variants=variants,
            notes=["所有方案使用同一留出集与相关文档标签，主指标为 Recall@10。",
                   "当前方案加入来源覆盖约束，降低同一文档切片占满候选列表的问题。"],
        )
    if run_id.startswith("parsing_"):
        specs = [("local_fast_only", "本地快速解析", "基线"), ("cloud_accurate_only", "云端精确解析", "对照"),
                 ("auto_router", "智能解析路由", "当前方案")]
        variants = [_variant(data, variant_id=item, label=label, role=role, root=(item,), metrics=parsing_metrics)
                    for item, label, role in specs]
        return EvaluationRunDetail(
            run_id=run_id, title="复杂文档解析路由控制实验", category="文档解析",
            dataset="原生 PDF、扫描 PDF、XLSX 各 10 份控制样本", split="固定控制集", sample_count=30,
            source=source, variants=variants,
            notes=["表格保留率由单元格、表头和数值召回共同计算。",
                   "云端对照在本次环境调用失败，错误数和云调用数均保留展示，不能将失败结果解释为质量基线。"],
        )

    public_metrics = [
        ("table_retention_score", "表格保留率", "ratio", ("table_retention_score",)),
        ("cell_recall", "单元格召回", "ratio", ("cell_recall",)),
        ("header_recall", "表头召回", "ratio", ("header_recall",)),
        ("numeric_recall", "数值召回", "ratio", ("numeric_recall",)),
        ("mean_latency_s", "平均延迟", "seconds", ("mean_latency_s",)),
        ("ok_rate", "成功率", "ratio", ("ok_rate",)),
    ]
    specs = [("pymupdf_text_only_pdf", "PyMuPDF 纯文本", "公开基线"),
             ("router_auto_pdf", "智能解析路由", "当前方案"),
             ("rapidocr_direct_image", "RapidOCR 图像直读", "对照")]
    variants = [_variant(data, variant_id=item, label=label, role=role, root=("summary", item), metrics=public_metrics)
                for item, label, role in specs]
    return EvaluationRunDetail(
        run_id=run_id, title="PubTables-1M 公共表格解析评测", category="文档解析",
        dataset=str(data["dataset_id"]), split=str(data["split"]), sample_count=int(data["sample_count"]),
        source=source, variants=variants,
        notes=["样本来自公开 PubTables-1M OTSL 测试集，并按最小单元格数量固定筛选。",
               "公开基线无法从文本层恢复表格，因此同时展示 OCR 对照，避免只与弱基线比较。"],
    )


@router.get("/overview", response_model=EnterpriseOverview)
async def get_enterprise_overview(current_user: EnterpriseReader, session: Session):
    events, _ = await list_audit_events(session, tenant_id=current_user.tenant_id, limit=200)
    documents = await list_documents(session, current_user.tenant_id)
    latest_conversations: dict[str, tuple[str, datetime | None]] = {}
    search_latencies = []
    actors = set()
    for event in events:
        actors.add(str(event["actor_id"]))
        action = str(event["action"])
        resource_id = str(event.get("resource_id") or "")
        if resource_id and action.startswith("chat.") and resource_id not in latest_conversations:
            latest_conversations[resource_id] = (action, _parse_event_time(event.get("occurred_at")))
        if action == "search.completed":
            latency = (event.get("metadata") or {}).get("elapsed_ms")
            if isinstance(latency, int | float):
                search_latencies.append(float(latency))
    stale_cutoff = datetime.now(UTC) - timedelta(minutes=10)
    actions = [
        "chat.cancelled" if action == "chat.requested" and occurred_at and occurred_at < stale_cutoff else action
        for action, occurred_at in latest_conversations.values()
    ]
    return EnterpriseOverview(
        observed_actors=sorted(actors),
        conversation_count=len(actions),
        completed_count=actions.count("chat.completed"),
        failed_count=actions.count("chat.failed") + actions.count("chat.cancelled"),
        waiting_count=actions.count("chat.waiting_input"),
        running_count=actions.count("chat.requested"),
        document_count=len(documents),
        healthy_document_count=sum(item.get("status") in {"completed", "ready"} for item in documents),
        search_count=sum(event["action"] == "search.completed" for event in events),
        average_search_ms=round(sum(search_latencies) / len(search_latencies)) if search_latencies else None,
        recent_events=events[:12],
    )


@router.get("/runtime", response_model=RuntimeSummary)
async def get_runtime_summary(current_user: EnterpriseReader):
    connections = _runtime_connections()
    return RuntimeSummary(
        agents=[RuntimeAgent(id=item.value, description=item.description) for item in SubAgentEnum],
        connections=connections,
        pipeline=["Supervisor", "领域智能体", "混合检索", "答案聚合", "合规审计"],
    )


@router.get("/runtime/agents/{agent_id}", response_model=RuntimeAgentDetail)
async def get_runtime_agent_detail(agent_id: str, current_user: EnterpriseReader):
    catalog = AGENT_CATALOG.get(agent_id)
    try:
        agent = SubAgentEnum(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="智能体不存在") from exc
    if catalog is None:
        raise HTTPException(status_code=404, detail="智能体运行清单不存在")
    connections = {item.id: item for item in _runtime_connections()}
    return RuntimeAgentDetail(
        id=agent.value,
        label=str(catalog["label"]),
        description=agent.description,
        source_module=str(catalog["source_module"]),
        capabilities=list(catalog["capabilities"]),
        guardrails=list(catalog["guardrails"]),
        connections=[connections[item] for item in catalog["connection_ids"]],
    )


@router.get("/evaluation", response_model=EvaluationSummary)
async def get_evaluation_summary(current_user: EnterpriseReader):
    routing_path = EVALUATION_PATHS["routing_full_singlelabel_20260706_210622"]
    rag_path = EVALUATION_PATHS["rag_lambdamart_enriched_train1300_dev200_20260707"]
    parsing_path = EVALUATION_PATHS["parsing_full_20260706_220325"]
    pubtables_path = EVALUATION_PATHS["pubtables_public_50_20260707"]
    routing = _load_json(routing_path)
    rag = _load_json(rag_path)
    parsing = _load_json(parsing_path)
    pubtables = _load_json(pubtables_path)
    enterprise_routing = routing["metrics"]
    holdout = rag["holdout"]
    return EvaluationSummary(metrics=[
        EvaluationMetric(
            id="routing_accuracy",
            label="企业路由准确率",
            baseline=enterprise_routing["single_llm_router"]["source_accuracy"]["enterprise_curated"],
            current=enterprise_routing["langgraph_supervisor"]["source_accuracy"]["enterprise_curated"],
            unit="ratio",
            sample_count=120,
            source=routing_path,
            run_id="routing_full_singlelabel_20260706_210622",
        ),
        EvaluationMetric(
            id="recall_at_10",
            label="多跳 Recall@10",
            baseline=holdout["vector_only"]["recall_at_10"],
            current=holdout["lambdamart_source_coverage"]["recall_at_10"],
            unit="ratio",
            sample_count=755,
            source=rag_path,
            run_id="rag_lambdamart_enriched_train1300_dev200_20260707",
        ),
        EvaluationMetric(
            id="table_retention",
            label="控制样本表格保留",
            baseline=parsing["local_fast_only"]["table_retention_score"],
            current=parsing["auto_router"]["table_retention_score"],
            unit="ratio",
            sample_count=parsing["auto_router"]["sample_count"],
            source=parsing_path,
            run_id="parsing_full_20260706_220325",
        ),
        EvaluationMetric(
            id="pubtables_retention",
            label="PubTables 表格保留",
            baseline=pubtables["summary"]["pymupdf_text_only_pdf"]["table_retention_score"],
            current=pubtables["summary"]["router_auto_pdf"]["table_retention_score"],
            unit="ratio",
            sample_count=pubtables["sample_count"],
            source=pubtables_path,
            run_id=pubtables["run_id"],
        ),
        EvaluationMetric(
            id="cloud_calls",
            label="云解析调用次数",
            baseline=float(parsing["cloud_accurate_only"]["cloud_call_count"]),
            current=float(parsing["auto_router"]["cloud_call_count"]),
            unit="count",
            sample_count=parsing["auto_router"]["sample_count"],
            source=parsing_path,
            run_id="parsing_full_20260706_220325",
        ),
    ])


@router.get("/evaluation/runs/{run_id}", response_model=EvaluationRunDetail)
async def get_evaluation_run_detail(run_id: str, current_user: EnterpriseReader):
    return _evaluation_run_detail(run_id)


@router.get("/evaluation/report", response_class=FileResponse)
async def download_evaluation_report(current_user: EnterpriseReader):
    path = (REPO_ROOT / "evals/reports/final_resume_metrics.md").resolve()
    return FileResponse(path, media_type="text/markdown; charset=utf-8", filename="企业多智能体量化实验汇总.md")
