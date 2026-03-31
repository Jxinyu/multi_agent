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
    "transport": "streamable-http",
    "headers": {
        "Authorization": "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJkZXZfdXNlciIsImlzcyI6Imh0dHA6Ly94aW55dXUuY29tIiwiaWF0IjoxNzczNTYzOTcyLCJleHAiOjE3NzM1Njc1NzIsImF1ZCI6Im15LWRldi1zZXJ2ZXIiLCJzY29wZSI6Inhpbnl1IGludm9rZXJfdG9vbHMifQ.l5yUxNsx_bNP368QMqV2bluuC20NpgyYs3pE0fsDIEAhk-uE8-BbNYa1wCTTOhiv7iTKsQISNhW82lVXE6eUQPhwd-leVf710WVSx3_iCYFfKk6WeISbbMzetFzP5sIhJTacHyDxsOEpvwqkjjNrBuFgoP6KhWQVfifLo0OXyr-ZUVzn3B05-Wbkz2BlmnDQtLFQA6pjtZWL0BMrImqP7sYv-D6nV6mWYSLzvD64htgJPKMQ1vnyXtrgeTqx8HUFcHo8ohgltOcGm0n0Ghul3SAHe5XL2g7rWWfvkeM_E5QbozYIV8fbK_jRbZ5hLykoBox0ICTcsnVOw3IV53KkIw",
    }

}


# MCP的客户端
mcp_client = MultiServerMCPClient({
    "python_mcp": python_mcp_server_config,
})


async def create_agent_self():
    """必须在异步函数中"""
    my_tool = await mcp_client.get_tools()

    return create_agent(
        model,
        tools=my_tool,
        system_prompt="你是一个智能助手。尽可能的调用工具回答用户的问题"
    )


async def main():
    # 1. 异步创建 Agent
    agent = await create_agent_self()

    question = "生成一段祝福语"

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















