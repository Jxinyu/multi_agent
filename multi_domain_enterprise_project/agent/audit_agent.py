import logging
from typing import Annotated, Dict, List

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from multi_domain_enterprise_project.core.model import qwen_model
from multi_domain_enterprise_project.core.task_state import TaskState, TaskStatus
from multi_domain_enterprise_project.core.task_state import TaskStatus

logger = logging.getLogger(__name__)


class AuditOutputFormat(BaseModel):
    """
    输出格式
    """
    is_pass: bool = Field(..., description="是否通过")
    correction_targets: str = Field(
        default="",
        description='如果is_pass为false，明确指出需要修正的Agent名称和修正指令。例如："需要 hr Agent 补充离职流程中的资产交接步骤"；如果is_pass为true，此字段输出空字符串。'
    )


async def audit_agent(state: TaskState, config: RunnableConfig):
    """收集子Agent返回的答案，并进行整理。消除重复或冲突，合成一段逻辑连贯、主次分明的最终回答，并统一整理所有引用来源。"""
    # 获取aggregator Agent的输出
    content = (state.sub_agent_response or {}).get("aggregator", {})
    if not content:
        return {
            "audit_feedback": None,
            "task_status": TaskStatus.FAILED,
            "result": {
                "最终回复": "当前没有可审核的聚合结果，请重新派发任务。",
                "参考资料": []
            },
            "messages": [HumanMessage(content="【系统提示】当前没有可审核的聚合结果。")]
        }

    logger.info(f"【Audit Agent的输入】: {content.get('回复内容', '')[:10]}...")

    system_prompt = """
    # 角色定位
    你是多智能体系统的“轻量审核员”。你的目标是避免明显风险，而不是做严格学术审稿。

    # 审核重点（只看两件事）
    1. 是否包含敏感内容（最高优先级）。
    2. 是否给出参考来源（有引用即可，不强求完美格式）。

    # 一、敏感内容审核规则（红线）
    发现以下任一情况，必须判定为不通过（is_pass=False）：
    - 违法违规指引：教唆违法、规避监管、伪造材料、洗钱、诈骗等。
    - 明显危险行为：武器制作、爆炸/毒害、恶意攻击系统、传播恶意代码等可执行危害指令。
    - 严重隐私泄露：身份证号、手机号、银行卡、住址、账户密钥、内部凭据等可识别敏感信息被直接暴露。
    - 歧视仇恨、暴力煽动或其他明显不当内容。
    - 违反公司安全规范的高风险操作建议（如泄露内部系统口令、越权访问、绕过审计）。

    # 二、参考来源审核规则（宽松）
    - 回答中只要提供了可追溯的参考来源（如文档名、条款名、检索片段、来源列表）即可判定“有参考”。
    - 不要求每句话都带引用，不要求引用格式统一，不因表达风格或结构问题打回。
    - 若内容整体可用但缺少参考来源，可打回并仅要求补充来源。

    # 判定逻辑（从宽）
    - 通过 (is_pass=True)：未发现敏感内容，且给出了参考来源。
    - 不通过 (is_pass=False)：
      - 存在任意敏感内容；或
      - 完全没有参考来源。

    # correction_targets 输出要求
    - 若因敏感内容不通过：明确指出“哪个专家 + 哪段内容 + 风险类型 + 修改建议（删除/改写为合规表述）”。
    - 若仅因缺少参考不通过：明确指出“请补充对应参考来源（文档名/条款/检索片段）”。
    - 语气简洁直接，不要额外扩展无关要求。
        """
    # 创建agent
    agent = create_agent(
        model=await qwen_model(),
        system_prompt=system_prompt,
        response_format=AuditOutputFormat,
    )

    response = await agent.ainvoke(input={"messages": [{"role": "user", "content": str(content)}]}, config=config)

    response = response['structured_response']

    logger.info(f"【Audit Agent的回复】: {response.is_pass}...")

    retry_count = state.retry_count
    max_retries = state.max_retries

    if (not response.is_pass) and (retry_count < max_retries):
        # 审核不通过，保留聚合结果并生成结构化反馈
        feedback_text = f'审计反馈：\n"correction_targets": {response.correction_targets}'
        return {
            "messages": [HumanMessage(content=feedback_text)],
            "task_status": TaskStatus.RETRYING,
            "audit_feedback": {
                "correction_targets": response.correction_targets,
                "retry_count": retry_count + 1
            },
            "retry_count": retry_count + 1
        }

    # 审核通过：统一输出键名，和 run_agent/run_agent_stream 的读取逻辑保持一致
    final_reply = content.get("回复内容", "")
    final_references = content.get("参考资料", [])
    return {
        "task_status": TaskStatus.COMPLETED,
        "audit_feedback": None,
        "sub_agent_response": {},
        "sub_agent_input_content": {},
        "pending_sub_agents": [],
        "finished_sub_agents": [],
        "result": {
            "最终回复": final_reply,
            "参考资料": final_references
        },
        "messages": [HumanMessage(content=f"【所有领域专家的最终答复】{final_reply}")]
    }
