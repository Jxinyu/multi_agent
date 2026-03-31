from typing import Annotated, Union, List, Dict
import logging

from langchain_core.messages import ToolMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.constants import END
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode, tools_condition, ToolRuntime
from langgraph.types import Checkpointer, Command, interrupt
from pydantic import Field

from multi_domain_enterprise_project.agent.tech_agent import tech_agent_node
from multi_domain_enterprise_project.agent.aggregator_agent import aggregator_agent
from multi_domain_enterprise_project.agent.audit_agent import audit_agent
from multi_domain_enterprise_project.agent.finance_agent import finance_agent
from multi_domain_enterprise_project.agent.hr_agent import hr_agent
from multi_domain_enterprise_project.agent.legal_agent import legal_agent
from multi_domain_enterprise_project.core.model import qwen_model
from multi_domain_enterprise_project.core.self_state import State
from multi_domain_enterprise_project.core.sub_agent_enum import SubAgentEnum

logger = logging.getLogger(__name__)


@tool
async def get_sub_agent_list() -> List[Dict]:
    """获取当前系统中所有可用的子代理专家列表及其能力描述。

    当你需要了解可用的专业子代理及其负责领域时，调用此工具。返回的列表中每个元素包含：
    - sub_agent_name: 子代理标识符（用于后续 invoke_sub_agent 工具调用）
    - description: 子代理的职责和能力说明
    在路由决策不确定时，可先调用此工具获取完整列表，以帮助判断将用户问题分发给哪个子代理。"""
    logger.info(f"【get_sub_agent_list】")
    return [
        {"sub_agent_name": i.value, "description": i.description} for i in SubAgentEnum
    ]


@tool
async def invoke_sub_agent(sub_agent_name: Annotated[str, Field(..., description="子代理名称")],
                           content: Annotated[str, Field(...,
                                                         description="给专家下达的具体任务指令。警告：必须是陈述句指令，严禁在此处填写对用户意图的疑问！")],
                           runtime: ToolRuntime) -> Union[str, Command]:
    """向专家下发任务。如果用户问题涉及多个领域，可以被并发调用多次。"""
    try:
        operation = SubAgentEnum(sub_agent_name)
    except:
        return f"子代理 {sub_agent_name} 不存在,仔细检查子代理名称"
    logger.info(f"调用 {operation.value} 代理成功!")
    tool_call_id = runtime.tool_call_id
    return Command(
        goto=operation.value,
        update={
            "sub_agent_input_content": {operation.value: content},
            "messages": [
                ToolMessage(
                    content=f"调用 {operation.value} 代理成功! 等待审核结果",
                    name='invoke_sub_agent',
                    tool_call_id=tool_call_id
                )
            ]
        }
    )


@tool
async def human_in_loop(content: Annotated[str, Field(..., description="发送给用户的内容")], runtime: ToolRuntime):
    """当用户问题模糊或置信度低时，使用此工具向用户提问以获取更多信息。"""
    if not content:
        return "输入的内容为空"
    decision = interrupt({
        "action": "human_decision",
        "content": content
    })
    if not decision:
        return "用户没有输入内容"
    return {"用户的回复": decision['content']}


async def create_graph(checkpointer: Checkpointer):
    # 定义工具列表
    tools = [get_sub_agent_list, invoke_sub_agent, human_in_loop]
    # 获取模型
    model = await qwen_model('qwen-max')
    # 定义工具节点
    too_node = ToolNode(tools)
    # 定义系统提示词
    system_prompt = """
    # 角色定位
    你是多代理系统的“交通枢纽”，负责接收用户问题，并将其路由给合适的领域专家Agent。**你不需要直接回答用户，只负责“分发任务”或“向用户追问”。**

    ## 模式识别
    根据当前对话状态，你会有两种工作模式：

    ### 模式一：首次路由
    当 **没有审计反馈（state 中 audit_feedback 为空）** 时，你处于首次路由模式：
    - 💡 **超级能力与严厉警告**：
      1. 你具备**并发调度**能力！如果用户的问题同时包含多个领域的意图，你**必须在一次回答中，并发生成多个 invoke_sub_agent 调用**！
      2. **严禁分批或分步处理！** 不允许先发两个任务等结果再发剩下的！必须一次性穷尽提取用户的所有意图并全部分发！
      3. **严禁工具混用**：绝不能在同一次回答中既调用 invoke_sub_agent 又调用 human_in_loop。

    - **工作流程**：
      1. 深挖用户意图，拆解出所有包含的专业领域。
      2. 执行动作：
         - 领域明确（置信度 ≥ 0.7）：并发调用多次 `invoke_sub_agent`，将拆解后的所有子任务一次性全部下发！
         - 信息模糊（置信度 < 0.7）：调用 `human_in_loop`，直接向用户提问澄清。

    ### 模式二：修正路由
    - ⚡️ 严厉警告：当你接收到审计反馈时，你【必须且只能】使用 `invoke_sub_agent` 工具重新下发修正指令！
    - 绝不允许使用自然语言进行回复或安抚（如“好的”、“已转交”、“马上处理”等废话）。只要你不输出工具调用，整个系统就会崩溃退出！
    - 审计反馈格式：
        "correction_targets": {
          "hr": "请补充离职流程中的资产交接步骤",
          "legal": "确保引用正确的法律条文，不要捏造"
        }
    """

    # model绑定系统提示词和工具
    agent = model.bind_tools(tools=tools)  # 绑定工具

    async def supervisor_agent(state: State, config: RunnableConfig):
        """它是整个多代理系统的“大脑”和“交通枢纽”，直接面向用户输入。"""
        sys_prompt = SystemMessage(content=system_prompt)

        messages = [sys_prompt] + state.messages

        logger.info(f"【supervisor_agent】开始执行: {state.messages[-1]}")
        response = []
        try:
            response = await agent.ainvoke(messages, config=config)
        except:
            logger.error(f"【supervisor_agent】执行错误")

        return {"messages": [response]}

    async def audit_router(state: State, config: RunnableConfig):
        """用于审核子代理的输出，并给出相应的反馈。"""
        audit_feedback = state.audit_feedback
        if not audit_feedback:
            return END
        logger.info(f"【audit_router】返回审核：{state.messages[-1]}")
        return "supervisor"

    graph = StateGraph(State)

    graph.add_node("supervisor", supervisor_agent)
    graph.add_node("tools", too_node)
    graph.add_node("tech", tech_agent_node)
    graph.add_node("hr", hr_agent)
    graph.add_node("finance", finance_agent)
    graph.add_node("legal", legal_agent)
    graph.add_node("aggregator", aggregator_agent)
    graph.add_node("audit", audit_agent)

    graph.set_entry_point("supervisor")
    graph.add_conditional_edges(
        "supervisor",
        path=tools_condition
    )
    graph.add_edge("tools", "supervisor")
    graph.add_edge("tech", "aggregator")
    graph.add_edge("hr", "aggregator")
    graph.add_edge("finance", "aggregator")
    graph.add_edge("legal", "aggregator")

    graph.add_edge("aggregator", "audit")

    graph.add_conditional_edges(
        "audit",
        path=audit_router
    )

    return graph.compile(checkpointer=checkpointer)
