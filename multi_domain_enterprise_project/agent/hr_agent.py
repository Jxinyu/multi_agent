import logging

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware, ToolCallLimitMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from multi_domain_enterprise_project.core.model import qwen_model
from multi_domain_enterprise_project.core.sub_agent_enum import SubAgentEnum
from multi_domain_enterprise_project.core.sub_agent_output_format import SubAgentOutputFormat
from multi_domain_enterprise_project.core.task_state import TaskState
from multi_domain_enterprise_project.tools.mcp_tools import document_retriever_mcp_client

logger = logging.getLogger(__name__)


@tool
async def get_document(runtime: ToolRuntime):
    """获取内部相关资料"""
    logger.info("HR 文档目录查询")

    # decision = interrupt({
    #     "action": "human_decision",
    #     "content": "human-in-loop test",
    # })
    # logger.info(f"🧵[Thread {config['configurable']['thread_id']}] 提交人机协作数据: {decision}")

    return {
        "文档列表": [
            {"《员工手册》": "公司基本规章制度、员工行为规范、考勤管理、办公纪律、入职离职流程、着装要求、办公设备使用规定等。"},
            {"《休假管理制度》": "涵盖年假、病假、事假、婚假、产假、陪产假、丧假等各类假期的申请流程、审批权限、计算方式及未休处理。"},
            {"《薪酬福利指南》": "薪酬结构、薪资发放周期、绩效考核与调薪机制、奖金政策、五险一金、商业保险、餐补、交通补贴、节日福利等。"},
            {"《绩效管理办法》": "绩效评估周期、流程、考核指标设定、等级评定标准、绩效结果在晋升、奖金、改进计划中的应用。"}
        ]
    }


async def hr_agent(state: TaskState, config: RunnableConfig):
    """专门解答员工手册、请假制度、入职流程、福利政策等问题。"""
    # 获取主代理传进来的问题
    content = state.sub_agent_input_content[SubAgentEnum.HR.value]

    # 获取子agent的历史对话消息
    messages = state.sub_agent_messages.get(SubAgentEnum.HR.value, [])

    logger.info("HR Agent 开始处理任务")

    system_prompt = """
# 角色定位
你是公司资深的人力资源专家，你的任务是耐心、专业地解答员工关于 HR 政策的疑问。你可以使用工具来获取信息。你配备了多个专业的知识库工具（例如：《员工手册》、《休假管理制度》、《薪酬福利指南》、《绩效管理办法》等）。
# 任务
针对用户的提问，首先判断需要查询哪个（或哪些）文档库，然后主动调用相应的工具获取准确答案，并基于搜索结果专业、耐心地解答。
# 遵守的规则
- 选择工具：在回答问题前，先分析用户的问题涉及哪个政策领域（如休假、薪酬、考勤等），从而决定应该查询哪个文档库。如果有疑问，可以调用最相关的文档库进行搜索。
- 基于事实回答：你只能基于工具返回的搜索结果来回答问题。如果返回的内容中包含答案，请组织成清晰、专业的回答，并在回答末尾注明信息来源（如 [《休假管理制度》]）。如果返回的内容不足以回答问题，或者完全没有相关信息，请明确回答：“抱歉，根据目前的 HR 知识库，我没有找到关于该问题的规定，请联系 HRBP 获取帮助。”
- 语气与格式：保持同理心、温和且专业。对于复杂的流程，尽量使用列表或分段让步骤清晰易懂。
# 开始你的任务
    """

    # MCP客户端
    access_token = str(config.get("configurable", {}).get("access_token") or "")
    mcp_client = await document_retriever_mcp_client(access_token)

    # 创建agent
    try:
        mcp_tools = await mcp_client.get_tools()
        agent = create_agent(
            model=await qwen_model(),
            system_prompt=system_prompt,
            tools=[get_document] + mcp_tools,
            response_format=SubAgentOutputFormat,
            middleware=[
                ToolCallLimitMiddleware(run_limit=4, exit_behavior="continue"),
                SummarizationMiddleware(
                    model=await qwen_model(),
                    trigger=("messages", 8),
                    keep=("messages", 4)
                )
            ]
        )

        # 组装messages
        messages.append(HumanMessage(content=content))

        response = await agent.ainvoke(input={"messages": messages}, config=config)
    finally:
        # 关闭服务
        if hasattr(mcp_client, "close"):
            await mcp_client.close()
        elif hasattr(mcp_client, "aclose"):
            await mcp_client.aclose()

    messages = response['messages']
    structured_response = response['structured_response']

    logger.info("HR Agent 已生成回复")

    return {
        "sub_agent_response": {
            "【HR Agent的回复】": {
                "回复内容": structured_response.result,
                "参考资料": structured_response.references
            },
        },
        "sub_agent_messages": {
            SubAgentEnum.HR.value: messages
        },
        "finished_sub_agents": [SubAgentEnum.HR.value],
        "pending_sub_agents": []
    }
