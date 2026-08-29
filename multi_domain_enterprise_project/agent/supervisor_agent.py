import logging
from typing import Annotated, Literal

from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.constants import END
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode, ToolRuntime, tools_condition
from langgraph.types import Checkpointer, Command, interrupt
from pydantic import BaseModel, Field

from multi_domain_enterprise_project.agent.aggregator_agent import aggregator_agent
from multi_domain_enterprise_project.agent.audit_agent import audit_agent
from multi_domain_enterprise_project.agent.finance_agent import finance_agent
from multi_domain_enterprise_project.agent.hr_agent import hr_agent
from multi_domain_enterprise_project.agent.legal_agent import legal_agent
from multi_domain_enterprise_project.agent.tech_agent import tech_agent_node
from multi_domain_enterprise_project.core.model import qwen_model
from multi_domain_enterprise_project.core.sub_agent_enum import SubAgentEnum
from multi_domain_enterprise_project.core.task_state import TaskState, TaskStatus

logger = logging.getLogger(__name__)


def _prepare_supervisor_state(state: TaskState) -> dict:
    """确定 supervisor 本次执行前需要写入的轮次状态。"""
    if state.task_status in {TaskStatus.IDLE, TaskStatus.COMPLETED, TaskStatus.FAILED}:
        return TaskState.round_reset_update()
    if state.audit_feedback:
        return {"task_status": TaskStatus.RETRYING}
    return {"task_status": state.task_status}


@tool
async def get_sub_agent_list() -> list[dict]:
    """获取当前系统中所有可用的子代理专家列表及其能力描述。

    当你需要了解可用的专业子代理及其负责领域时，调用此工具。返回的列表中每个元素包含：
    - sub_agent_name: 子代理标识符（用于后续 invoke_sub_agent 工具调用）
    - description: 子代理的职责和能力说明
    在路由决策不确定时，可先调用此工具获取完整列表，以帮助判断将用户问题分发给哪个子代理。"""
    logger.info("【get_sub_agent_list】")
    return [
        {"sub_agent_name": i.value, "description": i.description} for i in SubAgentEnum
    ]


class InvokeAgentModel(BaseModel):
    """定义invoke_sub_agent模型参数"""
    sub_agent_name: Annotated[Literal["finance", "tech", "legal", "hr"], Field(..., description="子代理名称，必须严格使用 finance、tech、legal、hr 之一，严禁编造新名称。")]
    content: Annotated[str, Field(...,description="给专家下达的具体任务指令。警告：必须是陈述句指令，严禁在此处填写对用户意图的疑问！")]


@tool
async def invoke_sub_agent(sub_agents: list[InvokeAgentModel],
                           runtime: ToolRuntime,
                           tool_call_id: Annotated[str, InjectedToolCallId]):
    """向领域专家下发任务。"""
    pending = list(runtime.state.pending_sub_agents or [])
    input_content = dict(runtime.state.sub_agent_input_content or {})
    finished = list(runtime.state.finished_sub_agents or [])
    requested = list(runtime.state.requested_agents or [])

    for agent in sub_agents:
        try:
            operation = SubAgentEnum(agent.sub_agent_name)
        except Exception:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=f"子代理 {agent.sub_agent_name} 不存在",
                            tool_call_id=tool_call_id,
                        )
                    ],
                    "task_status": TaskStatus.FAILED,
                }
            )

        is_retry_round = bool(runtime.state.audit_feedback)
        if (not is_retry_round) and (operation.value in finished):
            continue

        input_content[operation.value] = agent.content
        if operation.value not in pending:
            pending.append(operation.value)
        if operation.value not in requested:
            requested.append(operation.value)

    return Command(
        update={
            "messages": [
                ToolMessage(
                    content='{"status":"ok","message":"已登记待执行子代理"}',
                    tool_call_id=tool_call_id,
                )
            ],
            "task_status": TaskStatus.DISPATCHED,
            "requested_agents": requested,
            "pending_sub_agents": pending,
            "sub_agent_input_content": input_content,
        },
        goto="dispatcher",
    )


@tool
async def human_in_loop(content: Annotated[str, Field(..., description="发送给用户的内容")], runtime: ToolRuntime):
    """当用户问题模糊或置信度低时，使用此工具向用户提问以获取更多信息。"""
    if not content.strip():
        raise ValueError("追问内容不能为空")
    decision = interrupt({
        "action": "human_decision",
        "content": content
    })
    if not isinstance(decision, dict) or not str(decision.get("content") or "").strip():
        raise ValueError("用户回复为空")
    return {"用户的回复": decision['content']}


def _dispatch_pending_agents(state: TaskState) -> Command:
    """读取并消费待执行队列，避免同一批子代理被重复派发。"""
    sub_agent_names = list(state.pending_sub_agents or [])
    if not sub_agent_names:
        return Command(goto="aggregator", update={"task_status": TaskStatus.AGGREGATING})
    return Command(
        goto=sub_agent_names,
        update={
            "task_status": TaskStatus.EXECUTING,
            "pending_sub_agents": [],
        },
    )


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

    ## 可用子代理标识
    - `hr`：员工手册、请假、入职、离职、绩效、福利、劳动合同、人事流程。
    - `finance`：报销、预算、采购、发票、付款、成本中心、财务制度。
    - `legal`：合同、NDA、隐私、数据合规、知识产权、许可证、法律风险。
    - `tech`：API、系统架构、日志、部署、代码规范、项目 Wiki、内部技术文档。
    调用 `invoke_sub_agent` 时，`sub_agent_name` 必须严格使用以上四个标识之一，严禁编造 `legal_advisor`、`hr_specialist`、`data_privacy_expert` 等新名称。
    
    ## 核心判断原则
    1. 先判断信息是否足够，再决定是否分发或追问。
    2. 如果用户没有明确主问题、目标对象、流程名称、系统名称或业务边界，优先使用 `human_in_loop` 追问；如果可以明确判断所属领域，不要因为缺少员工身份、具体时间、金额、合同编号等下游执行参数而过早追问。
    3. 如果问题涉及多个领域，尽量一次性识别全部相关领域，并在同一次 `invoke_sub_agent` 中全部下发，避免拆分成多次。
    4. 如果只涉及单一领域，也要尽量保持任务边界准确，不要把无关子代理一起带上。
    
    ## 单一流程约束
    1. 对于首次路由：若需要分发子 agent，必须先调用 `get_sub_agent_list`，再根据返回结果调用 `invoke_sub_agent`。
    2. `get_sub_agent_list` 只能用于获取一次当前可用子代理列表；拿到列表后，不要重复调用它。
    3. 对于澄清类问题，如果主问题明显不明确、范围过宽、缺少关键上下文，直接调用 `human_in_loop`；但不要把轻微不完整也一律判成澄清。
    4. 多领域问题尽量一次性把所有相关子代理放进同一次 `invoke_sub_agent` 调用里；如果边界较模糊，宁可追问也不要只发一部分。
    5. 单领域问题避免过度联想，不要额外塞入无关子代理。
    
    ## 审计重试约束
    1. 当上下文中出现审计反馈时，进入“重试模式”。
    2. 重试模式下，优先直接调用 `invoke_sub_agent`，把修正后的任务一次性下发给需要修正的子代理。
    3. 重试模式下，不要再次调用 `get_sub_agent_list`。
    4. 如果审计反馈明确要求先向用户追问，才可以使用 `human_in_loop`；否则不要再次澄清。
    5. 重试时必须保留原始问题意图，并结合审计反馈补充遗漏内容、修正错误范围或错误对象。
    6. 重试指令要具体、可执行、可落地，不要只说“重新处理”“继续跟进”。
    
    ## 工作方式
    - 首次路由：先判断是否足够明确；不明确就直接追问，明确且需要分发时，先获取子代理列表，再分派。
    - 重试路由：有审计反馈时优先直接修正派发，不再重复走首次路由。
    - 你只输出工具调用，不输出自然语言回复。
    """

    # model绑定系统提示词和工具
    agent = model.bind_tools(tools=tools)  # 绑定工具

    async def supervisor_agent(state: TaskState, config: RunnableConfig):
        """它是整个多代理系统的“大脑”和“交通枢纽”，直接面向用户输入。"""
        sys_prompt = SystemMessage(content=system_prompt)
        messages = [sys_prompt] + state.messages
        state_update = _prepare_supervisor_state(state)
        next_status = state_update["task_status"]

        logger.info("Supervisor 开始执行 status=%s", next_status)
        response = []
        try:
            response = await agent.ainvoke(messages, config=config)
        except Exception:
            logger.exception("【supervisor_agent】执行错误")
            return {
                "task_status": TaskStatus.FAILED,
                "messages": [SystemMessage(content="supervisor 执行失败")]
            }

        return state_update | {
            "messages": [response],
        }

    def audit_router(state: TaskState, config: RunnableConfig):
        """用于审核子代理的输出，并给出相应的反馈。"""
        terminal_statuses = {TaskStatus.COMPLETED, TaskStatus.FAILED}
        if state.task_status in terminal_statuses:
            return END
        if state.audit_feedback:
            logger.info("Audit Router 要求重试")
            return "supervisor"
        return END

    def tools_condition_router(state: TaskState, config: RunnableConfig):
        last_message = state.messages[-1]
        route_map = {
            TaskStatus.DISPATCHED: "dispatcher",
            TaskStatus.EXECUTING: "dispatcher",
            TaskStatus.AGGREGATING: "aggregator",
            TaskStatus.AUDITING: "aggregator",
            TaskStatus.RETRYING: "aggregator",
        }
        if last_message.type != "tool":
            return "supervisor"
        if state.task_status in {TaskStatus.DISPATCHED, TaskStatus.EXECUTING} and state.pending_sub_agents:
            return route_map[state.task_status]
        return route_map.get(state.task_status, "supervisor")

    graph = StateGraph(TaskState)

    graph.add_node("supervisor", supervisor_agent)
    graph.add_node("tools", too_node)
    graph.add_node("dispatcher", _dispatch_pending_agents)
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
    graph.add_conditional_edges(
        "tools",
        path=tools_condition_router
    )

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
