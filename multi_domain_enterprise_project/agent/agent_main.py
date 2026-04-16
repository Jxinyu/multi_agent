import asyncio
import datetime
import sys
import logging

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from config import settings
from multi_domain_enterprise_project.agent.supervisor_agent import create_graph
from multi_domain_enterprise_project.core.task_state import TaskStatus

import os

os.environ["NO_PROXY"] = "localhost,127.0.0.1,modelscope.net,bigmodel.cn,xiaoai.plus"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_agent(query: str, config: dict, checkpointer) -> dict:
    """
    通用、无状态、防断网的 Agent 运行引擎。
    完美支持：单轮问答、多轮上下文对话、多轮连续人机协作(Interrupt)。
    """
    # 1. 初始化图 (如果 checkpointer 已传入，其实 create_graph 里的逻辑开销很小)
    agent = await create_graph(checkpointer)

    # 3. 探针：获取当前线程在数据库中的状态
    state = await agent.aget_state(config)

    try:
        # ==========================================
        # 核心路由逻辑：恢复中断 vs 正常追加对话
        # ==========================================
        if state and state.next:
            # 场景 A: 存在挂起的 Interrupt。说明用户现在的 query 是对 Agent 上一轮追问的【回复】
            logger.info(f"🧵[Thread {config['configurable']['thread_id']}] 从中断处恢复，提交人机协作数据: {query}")

            decision = {
                "content": query,
                "type": "approval",  # 配合你 tools 里的设计
            }
            # 使用 Command(resume) 精准恢复断点
            response = await agent.ainvoke(Command(resume=decision), config=config)

        else:
            # 场景 B: 正常的新问题 / 正常的多轮追加提问
            # 因为带有 thread_id，LangGraph 会自动把历史 message 拼在前面，不用你自己管理历史记录！
            logger.info(f"🧵 [Thread {config['configurable']['thread_id']}] 发起新一轮对话指令: {query}")

            response = await agent.ainvoke(
                {"messages": [{"role": "user", "content": query}]},
                config=config
            )

        # ==========================================
        # 结果处理逻辑：再次中断 vs 任务完成
        # ==========================================

        # 检查本轮图运行结束后，是否【再次】触发了人机交互 (多轮协作的关键)
        if '__interrupt__' in response:
            interrupt_data = response['__interrupt__'][0].value
            if interrupt_data.get('action') == 'human_decision':
                return {
                    "status": "waiting_for_user",
                    "message": interrupt_data['content'],
                    "references": []
                }

        # 如果没有 interrupt，说明 Graph 走到了 END，提取最终答案
        try:
            final_reply = response['result']['最终回复']
            references = response['result'].get('参考资料', [])
            return {
                "status": "completed",
                "message": final_reply,
                "references": references
            }
        except KeyError:
            last_msg = response['messages'][-1].content
            fallback_status = TaskStatus.COMPLETED if last_msg else TaskStatus.FAILED
            return {
                "status": fallback_status.value,
                "message": str(last_msg),
                "references": []
            }

    except Exception as e:
        logger.exception(f"❌ [Thread {config['configurable']['thread_id']}] 运行异常: {str(e)}")
        # 这里不要抛死，优雅地告诉前端发生了什么
        return {
            "status": "error",
            "message": f"系统开小差了，请稍后再试。错误信息: {str(e)}",
            "references": []
        }


STATUS_MESSAGES = {
    "supervisor": "🧠 调度中枢正在分析意图并规划任务...",
    "tools": "🛠️ 正在为您分发任务至专属领域专家...",
    "tech": "💻 技术专家正在查阅系统操作指南...",
    "hr": "🧑‍💼 HR专家正在比对人事制度与离职流程...",
    "finance": "💰 财务专家正在核对财务报销规范...",
    "legal": "⚖️ 法务专家正在审查合规与法律条文...",
    "aggregator": "📝 信息合成中心正在汇编专家的最终解答...",
}


def _resolve_stream_status(node_name: str, node_state: dict | None) -> dict | None:
    """把 LangGraph 节点事件映射成前端可消费的状态消息。"""
    if node_name == "audit":
        feedback = (node_state or {}).get("audit_feedback")
        message = "⚠️ 审计未通过，要求专家重新修正..." if feedback else "✅ 合规审计已通过，准备输出内容..."
        return {"type": "status", "message": message}

    message = STATUS_MESSAGES.get(node_name)
    if message:
        return {"type": "status", "message": message}

    return None


async def run_agent_stream(query: str, config: dict, checkpointer):
    """
    流式、无状态、防断网的 Agent 运行引擎。
    实时推流当前执行的进度状态给前端。
    """
    agent = await create_graph(checkpointer)
    state = await agent.aget_state(config)

    if state and state.next:
        logger.info(f"🧵[Thread {config['configurable']['thread_id']}] 从中断处恢复...")
        decision = {"content": query, "type": "approval"}
        input_data = Command(resume=decision)
    else:
        logger.info(f"🧵 [Thread {config['configurable']['thread_id']}] 发起新一轮对话指令...")
        input_data = {"messages": [{"role": "user", "content": query}]}

    try:
        # 使用 stream_mode="updates" 逐个捕获图中节点的执行完成事件
        async for event in agent.astream(input_data, config=config, stream_mode="updates"):
            # event 的格式例如：{"supervisor": {"messages": [...]}}
            for node_name, node_state in event.items():
                status_event = _resolve_stream_status(node_name, node_state)
                if status_event:
                    yield status_event

        # 图执行结束后（可能是 End，也可能是 Interrupt 挂起），提取最终状态
        final_state = await agent.aget_state(config)

        # 场景 A: 触发了人机交互挂起 (Interrupt)
        if final_state.next:
            interrupt_data = None

            # 🛠️ ：递归查找可能深藏在子 Agent (嵌套图) 中的中断数据
            def find_interrupt(snapshot):
                if (not snapshot) or (not hasattr(snapshot, 'tasks')) or (not snapshot.tasks):
                    return None
                for task in snapshot.tasks:
                    # 如果当前任务有中断，直接返回
                    if task.interrupts:
                        return task.interrupts[0].value
                    # 如果当前任务包含子图状态 (Sub-Graph)，向下一层穿透查找
                    if hasattr(task, 'state') and task.state:
                        res = find_interrupt(task.state)
                        if res:
                            return res
                return None

            # 提取中断数据
            interrupt_data = find_interrupt(final_state)

            if interrupt_data:
                logger.info(
                    f"⚠️ [Thread {config['configurable']['thread_id']}] 检测到子代理处于冻结状态，正在携带人类决策解冻...{interrupt_data}")
                action = interrupt_data.get('action')
                if action in ['human_decision', 'get_document']:
                    yield {
                        "type": "interrupt",
                        "message": interrupt_data['content'],
                        "references": []
                    }
                    return

        # 场景 B: 正常结束，提取最终回复
        result_data = final_state.values.get('result', {})
        if result_data:
            yield {
                "type": "complete",
                "message": result_data.get('最终回复', ''),
                "references": result_data.get('参考资料', [])
            }
        else:
            # 容错：兜底最后一条消息
            last_msg = final_state.values.get('messages', [])[-1].content
            yield {
                "type": "complete",
                "message": str(last_msg),
                "references": []
            }

    except Exception as e:
        logger.exception(f"❌ 运行异常: {str(e)}")
        yield {"type": "error", "message": f"系统开小差了，请稍后再试。错误信息: {str(e)}"}
