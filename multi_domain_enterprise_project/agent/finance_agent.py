import logging

from langchain.agents import create_agent
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from multi_domain_enterprise_project.core.sub_agent_enum import SubAgentEnum
from multi_domain_enterprise_project.core.sub_agent_output_format import SubAgentOutputFormat
from multi_domain_enterprise_project.tools.mcp_tools import finance_mcp_client
from multi_domain_enterprise_project.core.model import qwen_model
from multi_domain_enterprise_project.core.self_state import State

logger = logging.getLogger(__name__)


@tool
async def get_document(runtime: ToolRuntime):
    """获取当前用户有权限查看的内部财务文档列表及大纲。
    注意：本工具只返回文档的目录和简要说明，绝不包含具体的报销标准、数字和详细条款！
    详细条款必须通过企业知识库检索工具获取。"""
    config = runtime.config  # 获取运行时配置
    user_info = config['configurable']["user_info"]  # 获取用户信息
    # 接下来的流程
    # 根据不同用户的定位，搜索出不同的文档列表，然后return
    return {
        "提示": "以下仅为文档大纲，严禁直接使用大纲内容回答用户，必须调用检索工具查看详情！",
        "文档列表": [
            {"《差旅报销管理办法》": "涵盖国内/国际差旅的住宿、交通、餐饮补贴标准，报销审批流程，票据要求及超标申请流程。"},
            {"《费用报销细则》": "办公用品、培训费、业务招待费、通讯费等日常费用的报销范围、限额标准及附件要求。"},
            {"《固定资产管理制度》": "固定资产的定义、采购审批、入库登记、折旧计算、盘点周期及报废流程。"}
        ]
    }


async def finance_agent(state: State, config: RunnableConfig):
    """解答差旅报销规则、预算申请流程、采购 SOP 等问题。"""

    content = state.sub_agent_input_content[SubAgentEnum.FINANCE.value]  # 获取主代理传进来的问题

    logger.info(f"【Finance Agent的输入】: {content}")

    system_prompt = """
你是公司极其严谨的财务合规官。你的任务是解答员工关于报销、预算和财务制度的问题。

【核心规则】
1. 数据绝对准确：你对数字、额度限制极度敏感。绝不能捏造任何报销额度或财务规则。
2. 严格基于上下文：所有答案必须从检索内容中提取。
3. 引用机制：必须在每一条规则后加上引用来源。

【⚠️ 强制执行的工作流 (SOP) ⚠️】
你必须严格按照以下顺序执行操作，不可跳过任何一步：
第一步：调用 `get_document` 工具，获取当前可用的财务文档列表。
第二步：仔细分析用户问题，从列表中找到最匹配的文档名称（如“《差旅报销管理办法》”）。
第三步：**绝对核心** -> 你必须调用知识库检索工具，将上一步找到的文档名称作为参数传入，去检索真实的规章制度详情！
第四步：**严禁偷懒** -> 绝不能仅凭 `get_document` 返回的寥寥几句摘要就直接回答用户，你必须看到检索工具返回的详细正文后，才能开始撰写最终回答！如果检索出来的内容不足以回答用户问题时，就换种问题再次检索知识库，超过三次检索就直接回答用户
    """

    mcp_client = await finance_mcp_client()
    try:
        mcp_tools = await mcp_client.get_tools()
        agent = create_agent(
            model=await qwen_model(),
            system_prompt=system_prompt,
            tools=[get_document] + mcp_tools,
            response_format=SubAgentOutputFormat
        )
        response = await agent.ainvoke(input={"messages": [{"role": "user", "content": content}]}, config=config)
    finally:
        if hasattr(mcp_client, "close"):
            await mcp_client.close()
        elif hasattr(mcp_client, "aclose"):
            await mcp_client.aclose()

    # print(response)

    response = response['structured_response']

    logger.info(f"【Finance Agent的回复】: {response}")

    return {
            "sub_agent_response": {
                "【Finance Agent的回复】": {
                    "回复内容": response.result,
                    "参考资料": response.references
                },
            }
        }
