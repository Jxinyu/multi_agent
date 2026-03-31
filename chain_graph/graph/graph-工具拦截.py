import asyncio
from typing import Dict, Any, List

from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.messages import ToolMessage, AIMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.constants import END
from langgraph.graph import MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import InMemorySaver

from config import settings

import os
# 将相关域名加入白名单，强制直连（不走VPN代理）
os.environ["NO_PROXY"] = "localhost,127.0.0.1,modelscope.net,bigmodel.cn,xiaoai.plus"

mcp_client = MultiServerMCPClient(
    {
        "12306_mcp": {
            "transport": "streamable_http",
            "url": "https://mcp.api-inference.modelscope.net/fdc254277fdb4d/mcp"
        },
        "zhipu_mcp": {
            "url": "https://open.bigmodel.cn/api/mcp-broker/proxy/web-search/mcp?Authorization=163af72ae3d34e2ebb81919e05b5879b.6QoCjMulVygVKHtu",
            "transport": "streamable-http"
        }
    }
)

model = ChatOpenAI(
        model='deepseek-chat',
        api_key=settings.llm_key.deepseek,
        base_url='https://api.deepseek.com',
    )


class State(MessagesState):
    pass


async def intercept_tool(request: Dict[str, Any], execute: Any):
    """
    request: 包含 tool_call 字典(名称、参数), tool 实例, 以及 state 等信息
    execute: 执行真实工具的毁掉函数
    """
    tool_name = request.tool_call['name']
    tool_args = request.tool_call['args']
    tool_id = request.tool_call['id']

    print(f"准备执行的工具名称：{tool_name}")
    print(f"工具参数: {tool_args}")

    if tool_name == 'get-tickets':
        print(f"正在执行 get-tickets 工具, 查询 {tool_args['fromStation']} 到 {tool_args['toStation']} 余票信息")
        return ToolMessage(content="[系统拦截]：用户限额，禁止使用此MCP", tool_call_id=tool_id)

    try:
        result = await execute(request)
        return result
    except Exception as e:
        print("工具执行失败")
        raise e


async def create_graph():
    tools = await mcp_client.get_tools()

    tool_node = ToolNode(tools, awrap_tool_call=intercept_tool)

    builder = StateGraph(State)

    llm_with_tools = model.bind_tools(tools)

    async def chatbot(state: State):
        return {'messages': [await llm_with_tools.ainvoke(state['messages'])]}

    builder.add_node('chatbot', chatbot)
    builder.add_node('tools', tool_node)

    builder.set_entry_point('chatbot')
    builder.add_conditional_edges(
        source='chatbot',
        path=tools_condition,
    )
    builder.add_edge('tools', 'chatbot')

    return builder.compile()


async def run_graph():
    agent = await create_graph()
    res = await agent.ainvoke({"messages": [("user", "查询今天，上海到苏州的所有火车票")]})
    return res['messages'][-1].content


if __name__ == '__main__':
    print(asyncio.run(run_graph()))
