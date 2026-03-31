import asyncio

from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI

from config import settings

model = ChatOpenAI(
        model='gpt-3.5-turbo',
        api_key=settings.llm_key.xiaoAi,
        base_url='https://xiaoai.plus/v1',
        temperature=1.0,
        top_p=1.0,
    )

# python mcp 服务端连接配置
python_mcp_server_config = {
    "url": "http://127.0.0.1:8080/streamable",
    "transport": "streamable-http"

}
# 外网公开的mcp 服务端的连接配置  163af72ae3d34e2ebb81919e05b5879b.6QoCjMulVygVKHtu
zhipu_mcp_server_config = {
    "url": "https://open.bigmodel.cn/api/mcp-broker/proxy/web-search/mcp?Authorization=163af72ae3d34e2ebb81919e05b5879b.6QoCjMulVygVKHtu",
    "transport": "streamable-http"
}

# MCP的客户端
mcp_client = MultiServerMCPClient({
    "python_mcp": python_mcp_server_config,
    "zhipu_mcp": zhipu_mcp_server_config
})


async def create_agent_self():
    """必须在异步函数中"""
    my_tool = await mcp_client.get_tools()
    # print(my_tool)
    # mcp_prompt = await mcp_client.get_prompt(server_name="python_mcp", prompt_name="ask_about_topic", arguments={"topic": '深度学习'})
    # print(mcp_prompt)
    mcp_resource = await mcp_client.get_resources(server_name="python_mcp", uris="resource://config")
    print(mcp_resource[-1].data)

    return create_agent(
        model,
        tools=my_tool,
        system_prompt="你是一个智能助手。尽可能的调用工具回答用户的问题"
    )


async def main():
    # 1. 异步创建 Agent
    agent = await create_agent_self()

    question = "fastapi的使用方式以及官方文档开发地址"

    print(f"🗣️ 用户: {question}")
    print("🤖 Agent 正在思考并调用工具中...")

    res = await agent.ainvoke(
        {"messages": [("user", question)]}
    )

    print("\n✅ 最终回答:")
    print(res['messages'][-1].content)


if __name__ == '__main__':
    # 整个程序只有一个入口，把 main 扔进事件循环
    asyncio.run(main())















