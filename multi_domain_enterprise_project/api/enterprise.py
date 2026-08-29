from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
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
    connections = [
        RuntimeConnection(id="rag", label="企业 RAG MCP", configured=bool(settings.mcp.rag_url)),
        RuntimeConnection(id="web", label="网络搜索 MCP", configured=bool(settings.mcp.web_search_url)),
        RuntimeConnection(id="finance", label="财务图表 MCP", configured=bool(settings.mcp.finance_chart_url)),
        RuntimeConnection(id="legal", label="法务 MCP", configured=bool(settings.mcp.legal_url)),
    ]
    return RuntimeSummary(
        agents=[RuntimeAgent(id=item.value, description=item.description) for item in SubAgentEnum],
        connections=connections,
        pipeline=["Supervisor", "领域智能体", "混合检索", "答案聚合", "合规审计"],
    )


@router.get("/evaluation", response_model=EvaluationSummary)
async def get_evaluation_summary(current_user: EnterpriseReader):
    routing_path = "evals/results/routing/routing_full_singlelabel_20260706_210622/metrics.json"
    rag_path = "evals/results/rag/rag_lambdamart_enriched_train1300_dev200_20260707/metrics.json"
    parsing_path = "evals/results/parsing/parsing_full_20260706_220325/metrics.json"
    pubtables_path = "evals/results/parsing/pubtables_public_50_20260707/metrics.json"
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


@router.get("/evaluation/report", response_class=FileResponse)
async def download_evaluation_report(current_user: EnterpriseReader):
    path = (REPO_ROOT / "evals/reports/final_resume_metrics.md").resolve()
    return FileResponse(path, media_type="text/markdown; charset=utf-8", filename="企业多智能体量化实验汇总.md")
