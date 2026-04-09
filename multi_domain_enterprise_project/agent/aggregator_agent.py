import logging

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from multi_domain_enterprise_project.core.model import qwen_model
from multi_domain_enterprise_project.core.self_state import State
from multi_domain_enterprise_project.core.sub_agent_output_format import SubAgentOutputFormat

logger = logging.getLogger(__name__)


async def aggregator_agent(state: State, config: RunnableConfig):
    """收集子Agent返回的答案，并进行整理。消除重复或冲突，合成一段逻辑连贯、主次分明的最终回答，并统一整理所有引用来源。"""
    if state.pending_sub_agents != []:
        return Command(
            goto="supervisor",
            update={
                "messages": [SystemMessage(content=f"领域专家 【{state.pending_sub_agents}】 智能体执行失败，"
                                                   f"请重新向 【{state.pending_sub_agents}】 智能体下发任务。")]
            }
        )

    # 获取所有子代理的输出
    content = state.sub_agent_response

    logger.info(f"【aggregator_agent 的输入】: {content.keys()}")

    system_prompt = """
# 角色定位
作为信息合成Agent，你的任务是将多个专业领域Agent针对同一用户问题的碎片化回答整合成一份逻辑连贯、主次分明、无重复冲突的最终答案，并统一整理所有引用来源。你本身不生成新信息，只对已有的子回复进行组织和优化。
# 遵守的规则
- 信息整合：
  - 将各个子回答中相关的内容按逻辑顺序组织，形成一个统一的答案。
  - 消除冗余信息：如果多个子回答提到同一事实，只保留一次，但可合并表达。
  - 调和潜在冲突：如果不同子回答存在明显矛盾，尝试判断是否因角度不同（如“规定A”与“例外B”），若无法调和，需如实说明不同观点，并指出需进一步核实。
- 保持专业语气：用词准确、中立，适合企业环境。
# 处理步骤
1. 阅读原始问题：理解用户的核心诉求，确定最终答案需要覆盖哪些方面。
2. 梳理子回答：
  - 提取每个子回答的关键信息点和对应的引用。
  - 识别不同回答中重复或重叠的部分，标记可合并的内容。
  - 检查是否存在冲突：例如一个说“必须提前3天”，另一个说“提前5天”。分析冲突原因（可能是不同政策版本或领域角度不同），若无法解决，则如实呈现。
3. 构建答案框架：根据问题逻辑，决定信息呈现顺序（例如按领域顺序、按流程步骤、按重要性等）。
4. 撰写整合答案：
  - 用连贯的语言将关键信息串联起来，避免生硬拼凑。
  - 在每个信息点后标注引用来源。若同一信息点来自多个来源，可一并列出。
  - 如有冲突，在答案中说明差异。
    """
    # 创建agent
    agent = create_agent(
        model=await qwen_model(),
        system_prompt=system_prompt,
        response_format=SubAgentOutputFormat,
    )

    response = await agent.ainvoke(input={"messages": [{"role": "user", "content": str(content)}]}, config=config)

    response = response['structured_response']

    logger.info(f"【aggregator Agent的回复】: {response.result[:10]}")

    return {
        "sub_agent_response": {
            "aggregator": {
                "回复内容": response.result,
                "参考资料": response.references
            },
        },
    }
