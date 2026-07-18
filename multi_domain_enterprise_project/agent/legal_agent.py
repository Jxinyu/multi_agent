import logging

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from multi_domain_enterprise_project.core.model import qwen_model
from multi_domain_enterprise_project.core.sub_agent_enum import SubAgentEnum
from multi_domain_enterprise_project.core.sub_agent_output_format import SubAgentOutputFormat
from multi_domain_enterprise_project.core.task_state import TaskState
from multi_domain_enterprise_project.tools.mcp_tools import legal_mcp_client

logger = logging.getLogger(__name__)


@tool
async def get_document(runtime: ToolRuntime):
    """获取公司内部文档列表"""
    # 接下来的流程
    # 根据不同用户的定位，搜索出不同的文档列表，然后return
    return {
        "文档列表": [
            {
                "《保密协议模板与指引》": "涵盖公司标准保密协议（NDA）模板、签署流程、保密条款要点、违约责任说明，适用于与外部合作伙伴、客户或员工签署保密协议时参考。"},
            {
                "《数据保护与隐私政策》": "依据《个人信息保护法》（PDPA）及其他适用法规，规定个人信息收集、存储、使用、共享、删除的合规要求，以及数据泄露应急处理流程。"},
            {
                "《合同审核指南与模板库》": "包括销售合同、采购合同、劳动合同、技术开发合同等常用合同模板，及合同审核清单、风险点提示、修改建议示例。"},
            {
                "《反贿赂与反腐败政策》": "明确公司对商业贿赂、利益冲突的零容忍立场，规定礼品与招待限额、利益冲突申报流程、举报渠道及违规后果。"},
            {
                "《知识产权合规手册》": "涵盖专利、商标、著作权、商业秘密的管理与保护规则，员工在职期间及离职后的知识产权归属约定，开源代码使用规范。"}
        ]
    }


async def legal_agent(state: TaskState, config: RunnableConfig):
    """解答保密协议（NDA）、数据保护法（PDPA）、合同模板等合规类问题。"""

    content = state.sub_agent_input_content[SubAgentEnum.LEGAL.value]

    # 获取子agent的历史对话消息
    messages = state.sub_agent_messages.get(SubAgentEnum.LEGAL.value, [])

    logger.info("Legal Agent 开始处理任务")

    system_prompt = """
# 角色定位
作为公司的首席法务官兼合规专家，你配备了内部法律知识库搜索工具。
# 任务
针对用户的提问，主动判断是否需要查找相关法律政策，并自行调用“内部法律文档搜索”工具获取准确信息，然后基于搜索结果专业、严谨地解答。
# 遵守的规则
- 主动检索：在回答前，分析用户的问题涉及哪个法务领域（如合同条款、数据保护、保密协议等）。如果问题需要查询具体规定，必须调用工具，构造合适的搜索查询来获取最新、最准确的内部法律文档内容。
- 极度保守：法律无小事。你的回答必须极其精准，仅基于工具返回的【检索内容】，原文怎么规定的，你就怎么解释，不可自行引申或做过度宽泛的解读。
- 忠于上下文：只依赖工具返回的【检索内容】。如果返回的内容不足以回答问题，或者完全没有相关信息，请明确回答：“抱歉，根据内部法律知识库，我未能找到关于该问题的具体规定。建议你提交流程由法务部人工复核。”
- 严格引用：精准引用相关的法务条款或文档名称，在回答中标注来源（如 [《数据保护政策》第3.2条]）。
- 免责声明：在每次回答的末尾，必须强制加上这句话：```免责声明：以上回答基于公司内部知识库生成，仅供参考，不作为最终的法律意见。如遇重大法务决策，请务必提交流程由法务部人工复核。```
    """

    access_token = str(config.get("configurable", {}).get("access_token") or "")
    mcp_client = await legal_mcp_client(access_token)

    # 创建agent
    try:
        mcp_tools = await mcp_client.get_tools()
        agent = create_agent(
            model=await qwen_model(),
            system_prompt=system_prompt,
            tools=[get_document] + mcp_tools,
            response_format=SubAgentOutputFormat,
            middleware=[
                SummarizationMiddleware(
                    model=await qwen_model(),
                    trigger=("messages", 8),
                    keep=("messages", 4)
                )
            ]
        )
        # 组装messages
        messages.append({"role": "user", "content": content})

        response = await agent.ainvoke(input={"messages": messages}, config=config)
    finally:
        # 关闭服务
        if hasattr(mcp_client, "close"):
            await mcp_client.close()
        elif hasattr(mcp_client, "aclose"):
            await mcp_client.aclose()

    messages = response['messages']
    structured_response = response['structured_response']

    logger.info("Legal Agent 已生成回复")

    return {
        "sub_agent_response": {
            "【Legal Agent的回复】": {
                "回复内容": structured_response.result,
                "参考资料": structured_response.references
            },
        },
        "sub_agent_messages": {
            SubAgentEnum.LEGAL.value: messages
        },
        "finished_sub_agents": [SubAgentEnum.LEGAL.value],
        "pending_sub_agents": []
    }
