import logging

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from pydantic import Field

from multi_domain_enterprise_project.core.sub_agent_enum import SubAgentEnum
from multi_domain_enterprise_project.core.sub_agent_output_format import SubAgentOutputFormat
from multi_domain_enterprise_project.tools.mcp_tools import tech_mcp_client
from multi_domain_enterprise_project.core.model import qwen_model
from multi_domain_enterprise_project.core.task_state import TaskState

logger = logging.getLogger(__name__)


@tool
async def get_document(runtime: ToolRuntime):
    """获取内部文档列表"""
    config = runtime.config  # 获取运行时配置
    user_info = config['configurable']["user_info"]  # 获取用户信息
    # 接下来的流程
    # 根据不同用户的定位，搜索出不同的文档列表，然后return
    return {
        "文档列表": [
            {
                "《API开发规范与接口文档》": "公司内部 API 的设计规范、命名规则、认证方式、版本管理，以及各核心服务（用户服务、订单服务、支付服务等）的接口说明、请求响应示例。"},
            {
                "《系统架构设计文档》": "微服务架构概览、服务间通信协议（REST/gRPC/消息队列）、数据流图、关键技术栈说明（如 Spring Cloud、Kubernetes）、高可用与容灾设计。"},
            {
                "《代码规范与最佳实践》": "后端（Java/Python）编码规范、前端（React/Vue）代码风格、Git 提交规范、Code Review 流程、单元测试覆盖率要求。"},
            {"《数据库设计文档》": "各业务数据库的表结构、字段含义、索引策略、分库分表规则、数据迁移与备份方案。"}
        ]
    }


async def tech_agent_node(state: TaskState, config: RunnableConfig):
    """负责解答 API 文档、内部系统架构、代码规范、项目 Wiki 等问题。"""

    content = state.sub_agent_input_content[SubAgentEnum.TECH.value]  # 获取主代理传进来的问题
    # 获取子agent的历史对话消息
    try:
        messages = state.sub_agent_messages[SubAgentEnum.TECH.value]
    except:
        messages = []
    logger.info(f"【Tech Agent】的输入：{content[:10]}...")

    system_prompt = """
# 角色定位
作为公司的高级技术专家兼IT支持主管，你配备了多种查询工具（例如“内部技术文档搜索”和“网络搜索”）。
# 任务
针对用户的提问，主动判断是否需要查找信息，并自行调用合适的工具获取准确答案，然后基于搜索结果专业、清晰地解答。
# 遵守的规则
- 主动检索：在回答前，先分析问题涉及的范围。
  - 如果问题涉及公司内部系统、API、特定项目或内部技术细节，必须调用“内部技术文档搜索”工具。
  - 如果问题涉及通用技术概念、外部库、行业标准或需要最新信息，可以调用“网络搜索”工具。
  - 如果问题简单且你确信无需查询（例如常见编程语法），可以直接回答，但必须确保准确。
- 基于事实回答：你只能基于工具返回的信息来回答问题。如果返回的内容包含答案，请组织成清晰、专业的回答，并遵守以下格式要求：
  - 代码与技术细节：严格保留原始代码结构，使用 Markdown 代码块并标明语言（如 python,json）。
  - 逻辑清晰：解释系统架构或排障步骤时，使用有序列表（Step 1, Step 2...）。
  - 引用来源：在回答末尾标注信息来源（如 [内部文档: API指南] 或 [网络来源: MDN Web Docs]）。
- 知识边界：如果工具返回的信息不足以回答问题，或完全没有相关信息，请明确回答：“抱歉，根据现有资料无法找到该问题的确切答案，建议联系相关团队或查阅最新文档。” 绝不允许猜测未提供的参数或虚构信息。
    """

    mcp_client = await tech_mcp_client()

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

    final_result = structured_response.result
    logger.info(f"【Tech Agent】最终回复：{final_result[:10]}...")

    return {
        "sub_agent_response": {
            "【Tech Agent的回复】": {
                "回复内容": final_result,
                "参考资料": structured_response.references
            },
        },
        "sub_agent_messages": {
            SubAgentEnum.TECH.value: messages
        },
        "finished_sub_agents": [SubAgentEnum.TECH.value],
        "pending_sub_agents": []
    }
