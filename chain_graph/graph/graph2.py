import asyncio
from typing import Dict, Any, List

from langchain_core.messages import ToolMessage, AIMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.constants import END
from langgraph.graph import MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from config import settings

import os
# 将相关域名加入白名单，强制直连（不走VPN代理）
os.environ["NO_PROXY"] = "localhost,127.0.0.1,modelscope.net,bigmodel.cn,xiaoai.plus"

mcp_client = MultiServerMCPClient(
    {
        "12306_mcp": {
            # "type": "streamable_http",
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
        model='gpt-4o',
        api_key=settings.llm_key.xiaoAi,
        base_url='https://xiaoai.plus/v1',
    )


class State(MessagesState):
    pass


async def create_graph():
    tools = await mcp_client.get_tools()

    tool_node = ToolNode(tools)

    builder = StateGraph(State)

    llm_with_tools = model.bind_tools(tools)

    async def chatbot(state: State):
        return {'messages': [await llm_with_tools.ainvoke(state['messages'])]}

    def router(state: State):
        message = state['messages'][-1]
        if message.tool_calls:
            return 'tools'
        return 'end'

    builder.add_node('chatbot', chatbot)
    builder.add_node('tools', tool_node)

    builder.set_entry_point('chatbot')
    builder.add_conditional_edges(
        source='chatbot',
        path=tools_condition,
    )
    builder.add_edge('tools', 'chatbot')

    return builder.compile()


agent = asyncio.run(create_graph())




















