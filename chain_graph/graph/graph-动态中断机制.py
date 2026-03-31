import asyncio
from datetime import datetime
from typing import Dict, Any, List

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, wrap_tool_call
from langchain_core.messages import ToolMessage, AIMessage
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.constants import END
from langgraph.graph import MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition, ToolRuntime
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command
from pydantic import BaseModel, Field

from config import settings

import os

# 将相关域名加入白名单，强制直连（不走VPN代理）
os.environ["NO_PROXY"] = "localhost,127.0.0.1,modelscope.net,bigmodel.cn,xiaoai.plus"

mcp_client = MultiServerMCPClient(
    {
        "12306_mcp": {
            "transport": "streamable_http",
            "url": "https://mcp.api-inference.modelscope.net/fda524b6782f49/mcp",
            "headers": {
                "Authorization": "Bearer ms-2fb2d313-8f22-44ca-a6d6-5beee965b844"
            }
        },
        "zhipu_mcp": {
            "url": "https://open.bigmodel.cn/api/mcp-broker/proxy/web-search/mcp?Authorization=163af72ae3d34e2ebb81919e05b5879b.6QoCjMulVygVKHtu",
            "transport": "streamable-http"
        }
    }
)

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

zhipu_checkpoint = InMemorySaver()
one_checkpoint = InMemorySaver()

model = ChatOpenAI(
    model='qwen-plus',
    api_key=settings.llm_key.qwen,
    base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
)


class InvokerSubAgent(BaseModel):
    sub_agent_name: str = Field(..., description="子代理名称")
    content: str = Field(..., description="子代理处理内容")


@wrap_tool_call
async def warp_zhipu_tool(request: Dict[str, Any], handler: Any):
    tool_name = request.tool_call['name']
    tool_args = request.tool_call['args']
    tool_id = request.tool_call['id']
    print(f"工具调用前拦截，工具名称：{tool_name}， 工具参数：{tool_args}， 工具id：{tool_id}")
    return await handler(request)


@wrap_tool_call
async def warp_12306_tool(request: Dict[str, Any], handler: Any):
    tool_name = request.tool_call['name']
    tool_args = request.tool_call['args']
    tool_id = request.tool_call['id']
    print(f"工具调用前拦截，工具名称：{tool_name}， 工具参数：{tool_args}， 工具id：{tool_id}")
    return await handler(request)


@tool
async def query_search(query: str, runtime: ToolRuntime):
    """
    网络搜索
    """
    print("==============网络搜索开始执行")
    if query != "":
        decision = interrupt({
            "action": "require key",
            "message": "需要用户输入key",
        })
        if decision['type'] == 'approval':
            print(f"query_search 用户输入的key为：{decision['content']}")
        else:
            return "用户没有输入正确的key，网络搜索失败。（你可以告诉用户失败原因）"
    print(f"-=-=-=-=-=-=-=-=网络搜索结果")
    return "404 网页不存在"


async def sub_agent_zhipu():
    tools = [query_search]
    return create_agent(
        model=model,
        system_prompt="""
    你是一个专注于网络搜索的后台数据代理。
请根据用户输入的内容，尽可能搜索并使用Markdown整理客观的搜索结果。
【严格约束】：你是一个底层API。只返回事实、数据和总结内容！绝对不要包含任何客套话、问候语，绝对不要在结尾说“如果你需要什么请告诉我”、“很高兴为你服务”等交互性话语。
    """,
        tools=tools,
        middleware=[warp_zhipu_tool],
        checkpointer=zhipu_checkpoint
    )


async def sub_agent_one():
    one_tools = await one_mcp.get_tools()
    return create_agent(
        model=model,
        system_prompt="""你是12306查票后台代理。
根据日期、始发站和终点站，将所有的检索内容使用Markdown整理成表格返回。
【严格约束】：只返回纯粹的表格数据。不要加任何客套话、问候语或后续服务建议。""",
        tools=one_tools,
        middleware=[warp_12306_tool],
        checkpointer=one_checkpoint
    )


@tool
def get_subAgent(runtime: ToolRuntime):
    """
    获取可调用的subAgent
    """
    print("获取可调用的subAgent\n")
    user_id = runtime.config["configurable"]["user_id"]

    if user_id not in ['1', '2']:  # 人机交互
        return_interrupt = interrupt({  # 冻结
            "action": "require key",
            "message": "需要用户输入key",
        })
        # 解冻
        if return_interrupt['type'] == 'approval':
            print(f"用户输入的key为：{return_interrupt['content']}")
        else:
            return "用户没有输入正确的key，工具子agent列表失败。（你可以告诉用户失败原因）"
    return {"12306": "用于查询车票(需要输入日期、始发站、终点站)", "zhipu": "用于搜索网络内容"}


@tool(args_schema=InvokerSubAgent)
async def invoke_subAgent(sub_agent_name: str, content: str, runtime: ToolRuntime):
    """调用subAgent，完成任务"""
    tool_id = runtime.tool_call_id
    main_thread_id = runtime.config["configurable"]["thread_id"]

    if sub_agent_name not in ['12306', 'zhipu']:
        return "子代理不存在"
    if content == "":
        return "请输入内容"
    if sub_agent_name == '12306':
        print("12306子代理开始执行")

        config = {
            "configurable": {"thread_id": f"{main_thread_id}_12306"}
        }

        agent = await sub_agent_one()
    elif sub_agent_name == 'zhipu':
        config = {
            "configurable": {"thread_id": f"{main_thread_id}_zhipu"}
        }

        print("zhipu子代理开始执行")
        agent = await sub_agent_zhipu()
    else:
        return "子代理不存在"
    # ✅ 获取子代理的状态快照，判断是否处于挂起/中断状态
    state = await agent.aget_state(config)

    is_interrupt = hasattr(state, 'tasks') and len(state.tasks) > 0 and state.tasks[0].interrupts

    if is_interrupt:
        print("▶️ 检测到子代理处于冻结状态，正在携带人类决策解冻...")

        # 去除挂起时传出的payload
        interrupt_data = state.tasks[0].interrupts[0].value

        decision = interrupt(interrupt_data)

        res = await agent.ainvoke(Command(resume=decision), config=config)
    else:
        print("▶️ 正常执行子代理...")
        res = await agent.ainvoke(
            {"messages": [("user", content)]}
            , config=config)

    # 统一拦截新的中断！无论是初次执行还是解冻执行，只要大模型再次调用了需要人类介入的工具，这里就会生效
    if '__interrupt__' in res:
        interrupt_data = res['__interrupt__'][0].value
        # 在这里触发主agent挂起，把数据传给外部
        interrupt(interrupt_data)

        # 取出最终结果
        res = res['messages'][-1].content

        print(f"子 代理输出结果： {res}")

        return ToolMessage(
            content=f"子代理 {sub_agent_name} 的执行结果：\n\n{res}",
            tool_call_id=tool_id,
            name=sub_agent_name  # 可选，方便追踪
        )


@tool
def get_current_time():
    """获取当前日期和时间"""
    print("获取当前时间\n")
    return "当前时间是：" + str(datetime.now())


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
        print(
            f"\n⚠️ [系统告警] 正在请求执行 {tool_name} 工具, 查询 {tool_args.get('fromStation')} 到 {tool_args.get('toStation')}。")
        print("⏸️ [动态中断] 代码在此处挂起，等待人工审批...\n")

        # 调用interrupt，程序立马冻结，并把这个字典丢给外部/前端
        human_decision = interrupt({
            "action": "require_approval",
            "tool_name": tool_name,
            "tool_args": tool_args,
            "message": "用户正在尝试使用12306查票，是否允许？"
        })

        # 当外部调用Command后，代码从这里解冻/苏醒
        decision_type = human_decision.get('type')
        if decision_type == 'approve':
            print("✅ [人类反馈]：同意执行该工具！")
            return await execute(request)

        elif decision_type == 'reject':
            print(f"❌ [人类反馈]：拒绝执行！理由：{human_decision.get('reason')}")
            return Command(update={"messages": [ToolMessage(content="人类拒绝执行", tool_call_id=tool_id)]},
                           goto="chatbot")

        elif decision_type == 'edit':
            print(f"✏️ [人类反馈]：修改了查询参数为 {human_decision.get('new_args')}！")

            modified_tool_call = {**request.tool_call, "args": human_decision["new_args"]}
            modified_request = request.override(tool_call=modified_tool_call)

            return await execute(modified_request)

    try:
        print(f"👉 正常执行普通工具：{tool_name}...")
        result = await execute(request)
        return result
    except Exception as e:
        print("工具执行失败")
        raise e


async def create_graph():
    tools = [get_subAgent, invoke_subAgent, get_current_time]

    # tool_node = ToolNode(tools, awrap_tool_call=intercept_tool)
    tool_node = ToolNode(tools)

    builder = StateGraph(State)

    llm_with_tools = model.bind_tools(tools)

    async def chatbot(state: State):
        print("🤖：思考。。。")
        return {'messages': [await llm_with_tools.ainvoke(state['messages'])]}

    builder.add_node('chatbot', chatbot)
    builder.add_node('tools', tool_node)

    builder.set_entry_point('chatbot')
    builder.add_conditional_edges(
        source='chatbot',
        path=tools_condition,
    )
    builder.add_edge('tools', 'chatbot')

    return builder.compile(checkpointer=InMemorySaver())


async def run_graph():
    agent = await create_graph()

    # 对于人机交互，因为需要存档，所以必须提供config和thread_id，作为存档点
    config = {
        "configurable": {"thread_id": "thread_1", "user_id": "2"}
    }

    res = await agent.ainvoke({"messages": [("system", """你是一个多智能体系统的总控助手。
你的任务是理解用户需求，并调用合适的子代理(工具)来完成任务。绝对不要把工具的返回内容误认为是用户告诉你的，也绝对不要对子代理的返回结果说“谢谢”或进行对话。"""),
                                            ("user", "今日A股行情")]}, config=config)

    # ====== 第二步：捕捉抛出的检查点 ======
    # 检查并处理挂起（中断）
    interrupt_count = 1
    while '__interrupt__' in res.keys():
        # 获取我们刚才抛出的字典
        interrupt_data = res['__interrupt__'][0].value
        print(f"\n🚨 [外部感知 - 第{interrupt_count}次挂起] 收到系统中断！数据内容：{interrupt_data}")

        print("\n====== 第三步：人工介入处理 ======")
        # 模拟人工介入
        decision = {
            "type": "approval",
            "content": "key-sk123"
        }
        print(f"👩‍💻 管理员做出了决定：{decision}")

        print("\n====== 第四步：携带人类决策恢复运行 ======")
        # 使用Command将人类的决策送回代码，注意必须传入config
        res = await agent.ainvoke(Command(resume=decision), config=config)
        interrupt_count += 1

    print("\n🤖 [Agent 直接回复]：")
    return res['messages'][-1].content


if __name__ == '__main__':
    print(asyncio.run(run_graph()))
