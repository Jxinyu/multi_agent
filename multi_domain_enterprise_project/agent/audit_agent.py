import logging
from typing import Annotated, Dict, List

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from multi_domain_enterprise_project.core.model import qwen_model
from multi_domain_enterprise_project.core.self_state import State

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


async def audit_agent(state: State, config: RunnableConfig):
    """收集子Agent返回的答案，并进行整理。消除重复或冲突，合成一段逻辑连贯、主次分明的最终回答，并统一整理所有引用来源。"""
    # 获取aggregator Agent的输出
    content = state.sub_agent_response["aggregator"]

    logger.info(f"【Audit Agent的输入】: {content['回复内容'][:10]}...")

    system_prompt = """
    # 角色定位
    你是公司政令合规的“最后把关人”。你的唯一任务是：判断“最终回复”是否基于现有知识库【真正解决了】用户的原始问题，并确保回复中没有专家凭空捏造的虚假信息。

    # 核心审核准则（仅需满足以下三点即可通过）
    1. **意图覆盖率（是否答完）**：
       - 检查用户提问中的所有子问题是否都有回应。
       - **注意**：如果知识库中确实没有相关规定，而回复诚实地说明了“未查到相关制度，建议咨询XX部门”，这属于【完美解决】。绝对不要因为知识库缺失信息而责怪回复，只要它诚实且给出了后续建议即可。
    2. **事实严谨性（是否瞎编）**：
       - **红线规则**：严禁专家在没有获取到具体正文的情况下，根据文档标题或大纲猜测具体数字（如天数、金额）、法律条文或系统操作细节。
       - 如果你发现回复中出现了检索上下文（Context）中完全没有提到的具体规定（如“10个工作日”、“第XX条”），必须判定为“幻觉”并打回。
    3. **拒绝“过度审查”**：
       - 严禁要求回复提供用户【没问过】的信息。
       - 严禁因为语气不够优美或格式问题而打回。只要逻辑通顺、事实准确、回应了用户需求，就必须予以通过。
    # 判定逻辑
    - **通过 (is_pass=True)**：回复回应了用户的所有提问点（包括诚实告知查不到的情况），且所有事实陈述在上下文中均有据可查。
    - **打回 (is_pass=False)**：
      - 存在“幻觉”：回复中出现了上下文中没有的具体数字、时限或法律条款。
      - 存在“漏答”：用户明确问了某点，但回复完全没有提及（即便说没查到也算提及，完全不提才算漏答）。
    # 修改建议撰写规范
    如果审核未通过，请在 `correction_targets` 字段中明确指出：
    - “专家 XX 涉嫌凭空捏造了关于 XXX 的具体规定，请要求其重新基于正文检索，查不到请如实说明。”
    - “用户关于 XXX 的提问被遗漏了，请调度对应专家补充。”
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
        # 审核不通过
        return {
            "messages": [HumanMessage(content=f'审计反馈：\n"correction_targets": {response.correction_targets}')],
            "audit_feedback": f'审计反馈：\n"correction_targets": {response.correction_targets}',
            "retry_count": retry_count + 1
        }
    # 审核通过
    final_reply = content["回复内容"]
    return {
        "audit_feedback": None,
        "sub_agent_response": None,
        "sub_agent_input_content": None,
        "result": content,
        "messages": [HumanMessage(content=f"【最终结果】{final_reply}")]
    }
