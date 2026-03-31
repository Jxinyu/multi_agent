import asyncio
import os
import sys
from datetime import datetime
from typing import TypedDict, Annotated, Dict, Any, Optional
from langchain.agents import create_agent, AgentState
from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage, SystemMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.constants import END
from langgraph.graph import StateGraph, MessagesState
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode, ToolRuntime, tools_condition
from langgraph.types import Command, interrupt
from pydantic import Field, BaseModel
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import ConnectionPool, AsyncConnectionPool

from config import settings

# 将相关域名加入白名单，强制直连（不走VPN代理）
os.environ["NO_PROXY"] = "localhost,127.0.0.1,modelscope.net,bigmodel.cn,xiaoai.plus"

# 配置检查点链接
db_url = "postgresql://postgres:123123@127.0.0.1:5432/langgraph-multi"

# 配置mcp
zhipu_mcp = MultiServerMCPClient(
    {
        "zhipu_mcp": {
            "url": "https://open.bigmodel.cn/api/mcp-broker/proxy/web-search/mcp?Authorization=163af72ae3d34e2ebb81919e05b5879b.6QoCjMulVygVKHtu",
            "transport": "streamable-http"
        }
    }
)

one_mcp = MultiServerMCPClient({
    "12306_mcp": {
        "transport": "streamable_http",
        "url": "https://mcp.api-inference.modelscope.net/fda524b6782f49/mcp",
        "headers": {
            "Authorization": "Bearer ms-2fb2d313-8f22-44ca-a6d6-5beee965b844"
        }
    },
})

model = ChatOpenAI(
    model='qwen-plus',
    api_key=settings.llm_key.qwen,
    base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
)


# zhipu tool
async def get_zhipu_tools():
    """
    获取可用工具
    """
    zhipu_tool = await zhipu_mcp.get_tools()
    return zhipu_tool


# 12306 tool
@tool()
async def get_one_tools():
    """
    获取可用的工具
    """
    return await one_mcp.get_tools()


@wrap_tool_call
async def warp_zhipu_tool(request: Dict[str, Any], handler: Any):
    """zhipu工具调用拦截"""
    tool_name = request.tool_call['name']  # 工具名称
    tool_args = request.tool_call['args']  # 工具参数
    tool_id = request.tool_call['id']  # 工具id
    print(f"工具调用前拦截，工具名称：{tool_name}， 工具参数：{tool_args}， 工具id：{tool_id}")

    config = request.runtime.config
    user_info = config['configurable']["user_info"]

    if tool_name in ["webSearchPro", "webSearchStd"]:
        if user_info['user_id'] not in ['1', '2']:
            # 状态挂起
            decision_data = interrupt({
                "action": "require key",
                "message": "用户权限不足,需要输入权限key",
            })
            # 状态唤醒
            print(f"✔✔✔✔状态唤醒, 传入的数据为：{decision_data}")
    return await handler(request)


@wrap_tool_call
async def warp_one_tool(request: Dict[str, Any], handler: Any):
    """12306工具调用拦截"""
    tool_name = request.tool_call['name']
    tool_args = request.tool_call['args']
    tool_id = request.tool_call['id']
    print(f"工具调用前拦截，工具名称：{tool_name}， 工具参数：{tool_args}， 工具id：{tool_id}")

    return await handler(request)


class State(MessagesState):
    """
    状态图
    """
    sub_agent_call_id: Optional[str]
    sub_agent_content: Optional[str]


@tool()
async def get_subAgent(runtime: ToolRuntime):
    """
    获取可用的子代理
    """
    return [
        {"name": "web_search", "description": "网络搜索"},
        {"name": "query_ticket", "description": "查询火车票"}
    ]


@tool()
async def invoke_subAgent(sub_agent_name: Annotated[str, Field(..., description="子代理名称")],
                          content: Annotated[str, Field(..., description="子Agent需要处理什么事情?你需要具体告诉他")],
                          runtime: ToolRuntime):
    """调用子Agent"""
    if sub_agent_name not in ['web_search', 'query_ticket']:
        return "子代理不存在"
    if sub_agent_name == 'web_search':
        return Command(goto="web_sub_agent",
                       update={"sub_agent_call_id": runtime.tool_call_id, "sub_agent_content": content, "messages": [
                           ToolMessage(content=f"系统：已成功将任务移交给 {sub_agent_name} 子代理，请等待其返回结果。", tool_call_id=runtime.tool_call_id)]})
    elif sub_agent_name == 'query_ticket':
        return Command(goto="ticket_sub_agent",
                       update={"sub_agent_call_id": runtime.tool_call_id, "sub_agent_content": content, "messages": [
                           ToolMessage(content=f"系统：已成功将任务移交给 {sub_agent_name} 子代理，请等待其返回结果。",  tool_call_id=runtime.tool_call_id)]})


async def creat_graph(checkpoint):
    tools = [
        get_subAgent,
        invoke_subAgent
    ]

    tool_node = ToolNode(tools)

    model_binds_tool = model.bind_tools(tools=tools)

    async def web_search_subAgent(state: State, config: RunnableConfig):
        # 拿主agent传过来的数据
        content = state['sub_agent_content']
        if not content:
            return {"messages": [{"tool": "工具执行失败，没有输入任何值"}]}
        agent = create_agent(
            model=model,
            tools=await get_zhipu_tools(),
            middleware=[
                warp_zhipu_tool
            ],
            system_prompt="""
                你是一个网络搜索助手，根据输入的内容，尽可能的搜索更多的结果。结果中不要添加自己的思考、意见，只需要返回搜索到的内容即可。
                """
        )
        response = await agent.ainvoke({"messages": {"role": "system", "content": content}}, conig=config)

        final_content = response['messages'][-1].content
        return {"messages": [AIMessage(content=f"【Zhipu网络搜索子代理返回的结果】：\n{final_content}")]}

    async def query_ticket_subAgent(state: State, config: RunnableConfig):
        content = state['sub_agent_content']
        if not content:
            return {"messages": [{"tool": "工具执行失败，没有输入任何值"}]}
        agent = create_agent(
            model=model,
            tools=await get_one_tools,
            middleware=[
                warp_one_tool
            ],
            system_prompt="""
                        你是12306查票助手,根据日期、始发站、终点站查找两个目标城市之间的所有车票信息，结果直接使用markdown格式的表格输出，不要添加任何多余的内容
                        """
        )
        response = await agent.ainvoke({"messages": {"role": "system", "content": content}}, conig=config)

        final_content = response['messages'][-1].content
        return {"messages": [AIMessage(content=f"【12306查票子代理返回的结果】：\n{final_content}")]}

    async def supervisor(state: State):
        """主agent"""
        messages = state['messages']
        if not messages:
            return {"messages": [{"role": "system", "content": "输入的内容为空"}]}

        agent = await model_binds_tool.ainvoke(messages)

        return {"messages": [agent]}

    graph = StateGraph(state_schema=State)

    graph.add_node("supervisor", supervisor)
    graph.add_node("tools", tool_node)
    graph.add_node("web_sub_agent", web_search_subAgent)
    graph.add_node("ticket_sub_agent", query_ticket_subAgent)

    graph.set_entry_point("supervisor")
    graph.add_conditional_edges(
        "supervisor",
        path=tools_condition
    )
    graph.add_edge("tools", "supervisor")
    graph.add_edge("web_sub_agent", "supervisor")
    graph.add_edge("ticket_sub_agent", "supervisor")

    return graph.compile(checkpointer=checkpoint)


async def run_graph(query: str):
    """
    个人助理
    """
    async with AsyncPostgresSaver.from_conn_string(db_url) as checkpointer:
        agent = await creat_graph(checkpointer)

        system_prompt = """
        你是一个助手，你需要根据用户的输入，调用可用的工具进行智能处理，并给出相应的结果。
        """
        config = {
            "configurable": {"thread_id": f"thread_{str(datetime.now().timestamp())}", "user_info": {"user_id": "3"}}
        }

        response = await agent.ainvoke(
            {"messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": query}]},
            config=config
        )

        interrupt_count = 0
        while "__interrupt__" in response:
            # 人机交互
            interrupt_data = response["__interrupt__"][0].value
            print(f"🚨 [外部感知 - 第{interrupt_count}次挂起] 收到系统中断！数据内容：{interrupt_data}")

            decision = {"type": "approval", "content": "key-sk123"}

            print(f"👩‍💻 管理员做出了决定：{decision}")

            interrupt_count += 1
            response = await agent.ainvoke(Command(resume=decision), config=config)

        return response["messages"][-1].content


if __name__ == '__main__':
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        res = loop.run_until_complete(run_graph("帮我搜索关于提示词的网站"))
        print(res)
    finally:
        loop.close()
