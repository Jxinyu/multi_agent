from typing import TypedDict, List, Annotated, Sequence, Literal
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, START, END, add_messages
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode
from langgraph.store.redis import RedisStore

from config import settings

# 1. 导入 RedisSaver
from langgraph.checkpoint.redis import RedisSaver


class MessagesState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


# 2. 将 checkpointer 作为参数传入，方便在外部管理数据库连接生命周期
def create_graph(tools: List[BaseTool], checkpointer):
    llm = ChatOpenAI(
        model='gpt-3.5-turbo',
        api_key=settings.llm_key.xiaoAi,
        base_url='https://xiaoai.plus/v1',
        temperature=1.0,
        top_p=1.0,
    )
    tool_node = ToolNode(tools)
    llm_with_tools = llm.bind_tools(tools=tools)

    def router(state: MessagesState) -> Literal["tool", "end"]:
        message = state['messages'][-1]
        if message.tool_calls:
            return 'tool'
        return 'end'

    def call_model(state: MessagesState):
        messages = list(state['messages'])
        response = llm_with_tools.invoke(messages)
        return {'messages': [response]}

    workflow = StateGraph(MessagesState)
    workflow.add_node('model', call_model)
    workflow.add_node('tool', tool_node)

    workflow.set_entry_point('model')
    workflow.add_conditional_edges(
        'model', router,
        {'tool': 'tool', 'end': END}
    )
    workflow.add_edge('tool', 'model')

    # 3. 注入传进来的 Redis checkpointer
    return workflow.compile(checkpointer=checkpointer)


if __name__ == '__main__':
    from tool import all_tools  # 请确保路径正确

    # ==========================================
    # 4. 初始化 RedisSaver
    # ==========================================
    REDIS_URI = "redis://localhost:6379"

    # 官方推荐在脚本中使用 with 语句管理连接
    with RedisSaver.from_conn_string(REDIS_URI) as checkpointer:
        # ⚠️ 极其重要：首次连接必须调用 setup()，它会在 Redis 中创建所需的索引！
        checkpointer.setup()

        # 编译 Graph
        agent = create_graph(all_tools(), checkpointer=checkpointer)

        config = {'configurable': {'thread_id': 'user_lijinbiao_1'}}

        print("\n--- 第一轮对话 ---")
        res1 = agent.invoke(
            {'messages': [('user', '我是李锦彪')]},
            config=config  # 区分用户的唯一会话ID
        )
        print(res1['messages'][-1].content)

        print("\n--- 第二轮对话 ---")
        res2 = agent.invoke(
            {'messages': [('user', '我是谁？')]},
            config=config
        )
        print(res2['messages'][-1].content)

        rest = list(agent.get_state(config))
        print(rest)
